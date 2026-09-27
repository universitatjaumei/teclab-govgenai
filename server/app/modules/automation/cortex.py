"""
Cortex - Razonamiento de alto nivel para tareas de RPA y visión mediante IA.

Este módulo proporciona:
- Análisis de grabaciones para generar playbooks.
- Refinamiento de playbooks basado en feedback.
- Localización de elementos visuales mediante IA multimodal.
"""

import asyncio
import json
import logging
import re
import base64
from typing import List, Dict, Optional, Union, Tuple
from google import genai
from google.genai import types
import openai

# Importar el gestor de LLM existente
from server.app.modules.automation.infrastructure.llm_gateway import ejecutar_tarea
from server.app.services.api_key_service import get_api_key

# Issue #18 — los cuatro prefijos distintos que llevaba este modulo («[Brain/Cortex]»,
# «[Cortex]», «[analyze_recording_with_ai]», «[Cortex Vision Error]») son justamente lo que un
# nombre de logger resuelve sin que nadie tenga que acordarse de escribirlo.
logger = logging.getLogger(__name__)


def _clean_json_markdown(text: str) -> Union[List[Dict], Dict]:
    """Limpia el markdown de la respuesta JSON."""
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?\s*(.*?)\s*```"
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            text = matches[0]
    try:
        return json.loads(text)
    except Exception:
        return []


async def analyze_recording_with_ai(
    recording_logs: List[Dict],
    context_dict: Dict,
    config: Dict,
    system_prompt_override: Optional[str] = None,
) -> List[Dict]:
    """
    Analiza una secuencia de acciones grabadas y las generaliza en un Playbook.

    Transforma eventos de bajo nivel (clicks, tipos de teclado) en pasos
    automatizados resilientes utilizando selectores semánticos.

    Args:
        recording_logs: Lista de acciones capturadas durante la grabación.
        context_dict: Diccionario de variables globales para inyección de datos {{}}.
        config: Configuración del modelo y proveedor de IA.
        system_prompt_override: Plantilla de sistema opcional traída desde la BD.

    Returns:
        List[Dict]: Lista de pasos estructurados para el motor de ejecución.
    """
    logger.info("Analizando la grabacion con IA")

    # Seleccionar rol adecuado
    rol_to_use = config

    # Adaptacion para soportar tanto el dict completo de roles como un config especifico
    # Si 'config' tiene keys de roles, buscamos 'supervision' o 'logico_navegacion'
    # Si no, asumimos que 'config' ya es el rol o la configuracion del modelo.
    if isinstance(config, dict):
        if "supervision" in config:
            rol_to_use = config["supervision"]
        elif "logico_navegacion" in config:
            rol_to_use = config["logico_navegacion"]

    # 1. Preparar Contexto
    context_string = "Contexto vacio."
    if context_dict:
        context_string = json.dumps(context_dict, ensure_ascii=False)

    logs_context = json.dumps(recording_logs, ensure_ascii=False)

    # 2. Construir Prompt
    prompt = (
        system_prompt_override
        if system_prompt_override
        else f"""
    Eres un experto en automatizacion RPA y Playwright.

    OBJETIVO:
    Convertir un log de acciones de usuario ("recorded_actions") en un Playbook generalizado ROBUSTO.

    CONTEXTO DE DATOS (Variables disponibles):
    {context_string}

    ACCIONES GRABADAS:
    {logs_context}

    INSTRUCCIONES CLAVE (SELECTORES SEMANTICOS):
    El log ahora incluye informacion 'semantic' (etiquetas, texto, placeholders).
    TU PRIORIDAD ABSOLUTA es generar selectores RESILIENTES al cambio. EVITA selectores posicionales fragiles.

    JERARQUIA DE SELECTORES (Usa el primero que aplique):
    1. **Playwright explicito**: Si ves un texto claro o label.
       - `text="Guardar"`
       - `role="button", name="Enviar"`
       - `label="Nombre de usuario"`
       - `placeholder="Buscar..."`
    2. **XPath Semantico**:
       - `//input[@id='...']` (SOLO si el ID parece "humano" y estable, ej: 'username'. NO uses IDs generados ej: 'input-x9s').
       - `//button[contains(normalize-space(), 'Guardar')]`
       - `//input[preceding-sibling::label[contains(text(), 'Nombre')]]` (o parent label).
    3. **Atributos de Test**: `[data-testid="submit-btn"]`
    4. **CSS (Ultimisimo recurso)**: `#main div:nth-child(2) > input` (MARCAR COMO FRAGIL).

    OTROS REQUISITOS:
    1. **Smart Waits**: NO uses `wait` con tiempo fijo (ej: 5000) salvo que sea imposible detectar el estado. PREFIERE `action: "wait", selector: "..."` para esperar a que aparezca un elemento clave (ej: spinner desaparece, o resultado aparece).
    2. **Variables**: Si el valor coincide con el contexto {context_string}, usa {{{{Clave}}}}.
    3. **Archivos**: Si action="setInputFiles", usa `os.path.join(attachments_path, "{{{{NombreColumna}}}}")` si coincide con el contexto.
    4. **Login**: IGNORA pasos de login si la sesion ya existe.

    FORMATO DE PASO ESPERADO:
    {{
        "selector": "xpath_o_playwright_selector",
        "action": "click" | "fill" | "select" | "navigate" | "wait" | "setInputFiles",
        "value": "valor_o_variable",
        "description": "Explicacion semantica (ej: 'Clicar boton Guardar')"
    }}

    Responde SOLO con el JSON.
    """
    )

    res = await ejecutar_tarea(prompt, rol_to_use, script_origen="brain_cortex.py")

    if "response" in res:
        try:
            playbook = _clean_json_markdown(res["response"])
            if isinstance(playbook, list):
                return playbook
        except Exception:
            logger.exception("No se pudo interpretar la respuesta de la IA")

    return []


async def refine_playbook_with_ai(
    current_playbook: List[Dict],
    recording_logs: List[Dict],
    error_logs: str,
    user_feedback_history: List[str],
    context_data: Dict,
    config: Dict,
    system_prompt_override: Optional[str] = None,
) -> List[Dict]:
    """
    Refina un playbook existente utilizando logs de error y feedback humano.

    Actúa como un agente de "mantenimiento" que repara selectores obsoletos
    o añade pasos faltantes basándose en la discrepancia entre el éxito
    esperado y el resultado técnico reportado.

    Args:
        current_playbook: El playbook que presenta fallos.
        recording_logs: Logs originales de la grabación (opcional).
        error_logs: Traza de error técnica del motor de ejecución.
        user_feedback_history: Lista de comentarios del usuario sobre el fallo.
        context_data: Variables de entorno y datos de prueba.
        config: Configuración de IA (Tier 3 'supervision' recomendado).
        system_prompt_override: Plantilla de sistema para el refinador.

    Returns:
        List[Dict]: Playbook reparado y optimizado.
    """
    logger.info("Refinando el playbook con IA")

    # Seleccionar rol adecuado
    rol_to_use = config
    if isinstance(config, dict):
        if "supervision" in config:
            rol_to_use = config["supervision"]
        elif "logico_navegacion" in config:
            rol_to_use = config["logico_navegacion"]

    # Preparar contextos
    ctx_str = json.dumps(context_data, ensure_ascii=False) if context_data else "{}"
    logs_str = json.dumps(recording_logs, ensure_ascii=False)
    current_pb_str = json.dumps(current_playbook, ensure_ascii=False)
    feedback_str = "\n".join([f"- {f}" for f in user_feedback_history])

    hay_logs_originales = bool(recording_logs)

    prompt = (
        system_prompt_override
        if system_prompt_override
        else f"""
    Eres un experto en debugging de Playwright y RPA (Nivel Senior).

    OBJETIVO:
    Reparar un script de automatizacion JSON (Playbook) que esta fallando.

    ESTADO DE LA INFORMACION:
    - Tenemos logs de grabacion originales?: {"SI" if hay_logs_originales else "NO (MODO MANTENIMIENTO)"}

    DATOS DE ENTRADA:
    1. Contexto de Variables: {ctx_str}
    2. Logs de Grabacion Originales: {logs_str if hay_logs_originales else "NO DISPONIBLES"}
    3. Playbook Actual (Con Fallos): {current_pb_str}

    SINTOMAS DEL FALLO:
    - Error Tecnico Reportado: {error_logs}
    - Pistas del Humano:
    {feedback_str}

    INSTRUCCIONES DE REPARACION:

    CASO A) SI TIENES LOGS DE GRABACION (Recuperacion):
       - Los logs son la VERDAD ABSOLUTA de lo que queria hacer el usuario.
       - Usalos para reconstruir el paso que falta o esta mal en el Playbook.

    CASO B) SI NO TIENES LOGS (Mantenimiento Puro):
       - Asume que el 'Playbook Actual' FUNCIONABA BIEN antes, pero la web ha cambiado (Selectores obsoletos, botones movidos).
       - Tu mision es QUIRURGICA: Modifica SOLO el paso que ha dado error (mencionado en 'Error Tecnico') y sus dependencias directas.
       - NO re-inventes ni re-ordenes el script entero si no es imprescindible.
       - Basate fuertemente en el 'Feedback Humano' para saber que ha cambiado (ej: "Ahora el boton es azul").

    REGLAS GENERALES:
    1. Identifica el indice del paso fallido basandote en el error reportado.
    2. Genera un JSON valido con la lista completa de pasos corregida.
    3. Manten los pasos que funcionan intactos.

    Responde SOLO con el JSON (lista de objetos).
    """
    )

    res = await ejecutar_tarea(prompt, rol_to_use, script_origen="brain_cortex.py")

    if "response" in res:
        try:
            new_pb = _clean_json_markdown(res["response"])
            if isinstance(new_pb, list):
                return new_pb
        except Exception:
            logger.exception("No se pudo interpretar el JSON del playbook refinado")

    return current_playbook


async def locate_visual_element(
    image_bytes: bytes,
    element_description: str,
    viewport_size: dict,
    config: dict,
    system_prompt: str = None,
) -> Optional[Tuple[int, int]]:
    """
    Identifica las coordenadas (x, y) de un elemento visual mediante IA Multimodal.

    Utiliza capacidades de visión (como Gemini 2.0 Flash) para analizar capturas
    de pantalla y devolver la ubicación exacta de componentes que no son
    detectables mediante selectores DOM tradicionales.

    Args:
        image_bytes: Datos binarios de la imagen (PNG).
        element_description: Descripción textual del elemento (ej: "Icono de carrito").
        viewport_size: Tamaño de la ventana del navegador al capturar la imagen.
        config: Configuración del proveedor (Google/Vision).
        system_prompt: Instrucciones base para el agente de visión.

    Returns:
        Optional[Tuple[int, int]]: Coordenadas del centro del elemento o None si falla.
    """
    logger.info("Peticion de vision: %s", element_description)

    provider = config.get("provider", "").lower()
    model_id = config.get("model_id", "")

    # Warn if using defaults (indicates missing config)
    if not provider:
        logger.warning("Sin proveedor en la configuracion; se usa «google»")
        provider = "google"
    if not model_id:
        logger.warning(
            "Sin modelo en la configuracion; se usa «gemini-2.0-flash-exp»"
        )
        model_id = "gemini-2.0-flash-exp"

    logger.debug("Proveedor %s, modelo %s", provider, model_id)

    # Construir Prompt Final
    dims_str = f"{viewport_size.get('width', '?')}x{viewport_size.get('height', '?')}"
    user_msg = (
        f"Elemento a buscar: {element_description}. \nDimensiones Imagen: {dims_str}"
    )

    # Prompt System + User
    full_prompt_text = (system_prompt or "") + "\n\n" + user_msg

    response_json = {}

    try:
        if provider == "google":
            api_key = await get_api_key("google")
            if not api_key:
                logger.error("Sin credencial de Google: no se puede usar la vision")
                return None

            client = genai.Client(api_key=api_key)

            # Google GenAI Vision Call (Wrapped in thread to avoid blocking loop)
            def _call_vision():
                return client.models.generate_content(
                    model=model_id,
                    contents=[
                        full_prompt_text,
                        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    ],
                )

            response = await asyncio.to_thread(_call_vision)

            if response and response.text:
                response_json = _clean_json_markdown(response.text)

        elif provider == "openrouter" or provider == "openai":
            # For OpenRouter/OpenAI we usually need URL or Base64
            api_key = await get_api_key("openrouter")  # Or openai
            if not api_key:
                return None

            b64_image = base64.b64encode(image_bytes).decode("utf-8")

            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1"
                if provider == "openrouter"
                else None,
            )

            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": full_prompt_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64_image}"
                                },
                            },
                        ],
                    }
                ],
            )
            content = resp.choices[0].message.content
            response_json = _clean_json_markdown(content)

        else:
            logger.error("Proveedor de vision no soportado: %s", provider)
            return None

        # Parse Result
        # Expected: { "found": true, "x": 123, "y": 456, ... }
        if isinstance(response_json, dict) and response_json.get("found"):
            x = response_json.get("x")
            y = response_json.get("y")
            confidence = response_json.get("confidence", 0)
            reasoning = response_json.get("reasoning", "")

            if x is not None and y is not None:
                logger.info(
                    "Elemento localizado en (%s, %s), confianza %s: %s",
                    x,
                    y,
                    confidence,
                    reasoning,
                )
                return (int(x), int(y))

        logger.info(
            "Elemento no encontrado o con confianza baja; respuesta: %s", response_json
        )
        return None

    except Exception:
        logger.exception("Fallo la localizacion del elemento por vision")
        return None
