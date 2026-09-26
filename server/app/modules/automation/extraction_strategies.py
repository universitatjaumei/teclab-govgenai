"""
Extraction Strategies - Lógica de extracción de documentos impulsada por IA.

Este módulo contiene funciones puras para las diferentes fases de extracción:
- Fase 0: Descubrimiento de estructura documental.
- Fase 1: Extracción de precisión (vía LLM).
- Fase 2: Refinamiento con feedback del usuario.
- Fase 3: Generación de scripts deterministas autónomos.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from server.app.modules.automation.infrastructure.llm_gateway import (
    ejecutar_tarea,
    limpiar_respuesta_json,
)

# Issue #18 — estas funciones corren dentro de una peticion de extraccion.
logger = logging.getLogger(__name__)

# --- AI STRATEGIES (PURE FUNCTIONS) ---


async def analyze_document_structure(
    doc_text_a: str,
    doc_text_b: str,
    language_hint: str,
    config: Dict[str, Any],
    system_prompt: str = None,
) -> Dict[str, Any]:
    """
    Fase 0: Descubrimiento inteligente de campos potenciales.

    Analiza dos tipos de extracción de texto (lineal y con layout) para sugerir
    etiquetas relevantes, niveles de confianza y posibles números de página.

    Args:
        doc_text_a: Texto obtenido mediante motor de extracción lineal (fitz).
        doc_text_b: Texto obtenido respetando columnas y layout (pdfplumber).
        language_hint: Pista del idioma del documento (ej: 'es').
        config: Configuración de la IA para el descubrimiento (Tier 1/2).
        system_prompt: Plantilla de sistema inyectada desde el servidor.

    Returns:
        Dict[str, Any]: Diccionario con la lista de campos sugeridos.
    """
    if not system_prompt:
        system_prompt = f"""Eres un analista documental.
Devuelve SOLO JSON valido (sin comentarios, sin texto extra).
Idioma preferente: {language_hint}.
Tarea: sugerir nombres de campos (etiquetas) que parezcan relevantes.
Incluye 'score' [0..1] por confianza y 'page_hint' si puedes inferir la pagina."""

    user_prompt = f"""Analiza estos dos extractos del mismo documento:
[Vista A - lineal]
{doc_text_a[:15000]}

[Vista B - con layout]
{doc_text_b[:15000]}

Devuelve un JSON con este formato EXACTO:
{{
"fields": [
{{"name":"...", "score":0.95, "page_hint": 2}}
],
"format_ok": true
}}

Reglas:
- Maximo 100 elementos.
- 'name' conciso.
- 'score': confianza [0..1].
- 'page_hint': entero o null.
"""

    prompt_final = system_prompt + "\n\n" + user_prompt
    resultado = await ejecutar_tarea(
        prompt_final, config, script_origen="brain.extraction_strategies"
    )

    if "response" in resultado:
        return _safe_json_parse(resultado["response"])
    else:
        return {"fields": [], "format_ok": False, "error": resultado.get("error")}


def _safe_json_parse(text: str) -> Dict[str, Any]:
    """
    Parsea JSON permitiendo casos con ruido minimo.
    """
    import json
    import re

    if not text:
        return {"fields": [], "format_ok": False}

    # Recortar a bloque JSON
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        text = m.group(0)

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # Normalizar
            fields = []
            raw_fields = data.get("fields", [])
            if isinstance(raw_fields, list):
                for item in raw_fields:
                    if isinstance(item, dict):
                        try:
                            score = float(item.get("score", 0))
                        except Exception:
                            score = 0.0

                        ph = item.get("page_hint")
                        try:
                            page_hint = int(ph) if ph is not None else None
                        except Exception:
                            page_hint = None

                        fields.append(
                            {
                                "name": str(item.get("name", "")).strip(),
                                "score": score,
                                "page_hint": page_hint,
                            }
                        )
            return {"fields": fields, "format_ok": True}
        return {"fields": [], "format_ok": False}
    except Exception:
        return {"fields": [], "format_ok": False}


async def extraer_datos_precision(
    texto_fitz: str,
    texto_plumber: str,
    campos_seleccionados: List[str],
    definicion_usuario: str,
    config: Dict[str, Any],
    system_prompt: str,
    usar_tier_2: bool = False,
    ejemplos_validacion: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Fase 1 y 2: Extracción de datos de alta precisión mediante LLM.

    Combina ambas vistas de texto (fitz y plumber) para resolver la ubicación
    y el valor de los campos solicitados por el usuario. Soporta inyección
    de "few-shot" ejemplos para mejorar la consistencia.

    Args:
        texto_fitz: Texto extraído vía PyMuPDF (Estructura visual).
        texto_plumber: Texto extraído vía PDFPlumber (Tablas/Datos densos).
        campos_seleccionados: Lista de etiquetas técnicas a extraer.
        definicion_usuario: Contexto descriptivo de lo que se busca.
        config: Configuración de IA (Tier 1 por defecto, Tier 2 si se solicita).
        system_prompt: Plantilla de sistema formateada con variables.
        usar_tier_2: Si es True, utiliza modelos de razonamiento superior.
        ejemplos_validacion: Diccionario opcional con ejemplos de formato.

    Returns:
        Dict[str, Any]: Diccionario 'datos' con las claves extraídas.
    """
    rol_key = "logico_navegacion" if usar_tier_2 else "extraccion_pdf"

    # Strict Configuration Resolution (Tiering Strategy Enforcement)
    config_rol = None
    if isinstance(config, dict):
        if rol_key in config:
            config_rol = config[rol_key]
        else:
            # Fallback for flat config from AIBrainService
            if "provider" in config or "proveedor" in config:
                config_rol = config
    else:
        config_rol = config

    if config_rol is None:
        config_rol = {}

    if not system_prompt:
        raise ValueError("El prompt de sistema es obligatorio para la Fase 1.")

    # 1. Formatear el Prompt Base PRIMERO (Para evitar conflicto con las { } del JSON inyectado)
    prompt_extraccion = system_prompt.format(
        campos_list_str=", ".join(campos_seleccionados),
        definicion_usuario=definicion_usuario,
        texto_fitz=texto_fitz[:50000],
        texto_plumber=texto_plumber[:50000],
    )

    # 2. Inyectar Ejemplos (Si existen)
    if ejemplos_validacion:
        # Serializar ejemplos de manera bonita
        try:
            ejemplos_str = json.dumps(ejemplos_validacion, ensure_ascii=False, indent=2)
        except Exception:
            ejemplos_str = str(ejemplos_validacion)

        prompt_extraccion += f"\n\n>>> EJEMPLO DE FORMATO ESPERADO (Del primer archivo de este lote):\n{ejemplos_str}"

    resultado = await ejecutar_tarea(
        prompt_extraccion, config_rol, script_origen="brain.extraction_strategies"
    )

    if "response" in resultado:
        datos_limpios = limpiar_respuesta_json(resultado["response"])

        if isinstance(datos_limpios, dict) and "datos" not in datos_limpios:
            if all(
                isinstance(v, dict) and ("valor" in v or "pagina" in v)
                for v in datos_limpios.values()
            ):
                datos_limpios = {"datos": datos_limpios}

        return datos_limpios
    else:
        raise RuntimeError(f"Error en extraccion: {resultado.get('error')}")


async def refinar_extraccion_con_feedback(
    texto_fitz: str,
    texto_plumber: str,
    datos_anteriores: Dict[str, Any],
    feedback_usuario: str,
    config: Dict[str, Any],
    system_prompt: str,
) -> Dict[str, Any]:
    """
    Fase 1 (Refinamiento): Re-extraccion inteligente guiada por correcciones del usuario (Prompt Inyectado).
    """
    config_rol = (
        config.get("logico_navegacion", config)
        if isinstance(config, dict) and "logico_navegacion" in config
        else config
    )

    if not system_prompt:
        raise ValueError("El prompt de sistema es obligatorio para el Refinamiento.")

    prev_json_str = json.dumps(datos_anteriores, ensure_ascii=False)

    prompt_refinamiento = (
        system_prompt.replace("{texto_plumber}", texto_plumber[:45000])
        .replace("{texto_fitz}", texto_fitz[:45000])
        .replace("{previous_json}", prev_json_str)
        .replace("{validated_json}", prev_json_str)
        .replace("{feedback_usuario}", feedback_usuario)
    )

    resultado = await ejecutar_tarea(
        prompt_refinamiento, config_rol, script_origen="brain.extraction_strategies"
    )

    if "response" in resultado:
        return limpiar_respuesta_json(resultado["response"])
    else:
        raise RuntimeError(f"Error en refinamiento: {resultado.get('error')}")


async def generar_script_determinista(
    docs_text_list: List[Dict[str, str]],
    campos_objetivo: List[str],
    config: Dict[str, Any],
    system_prompt: str,
    valores_ejemplo: Optional[Dict] = None,
    info_descubrimiento: Optional[Dict] = None,
    feedback_usuario: str = None,
    tabla_auditoria: str = None,
    field_definitions: Optional[List[Dict]] = None,
) -> str:
    """
    Fase 3: Genera código Python para la extracción autónoma (Determinista).

    Crea funciones basadas en expresiones regulares o búsqueda de anclajes (Anchor-Based)
    analizando patrones comunes entre múltiples documentos de entrenamiento.

    Args:
        docs_text_list: Lista de documentos de entrenamiento con sus textos.
        campos_objetivo: Nombres de los campos que el script debe resolver.
        config: Configuración de IA (Tier 3 'supervision' requerido).
        system_prompt: Instrucciones detalladas para el generador de código.
        valores_ejemplo: Mapeo de campos a valores reales conocidos (Ground Truth).
        info_descubrimiento: Datos de estructura obtenidos en la Fase 0.
        feedback_usuario: Ajustes manuales solicitados durante la iteración.
        tabla_auditoria: Informe de fallos de versiones previas del script.
        field_definitions: Metadatos sobre la naturaleza de los campos (Anclajes).

    Returns:
        str: Script Python autónomo listo para integrarse en un flujo.
    """
    config_rol = (
        config.get("logico_navegacion", config)
        if isinstance(config, dict) and "logico_navegacion" in config
        else config
    )

    if not system_prompt:
        raise ValueError(
            "El prompt de sistema es obligatorio para la Generacion de Scripts."
        )

    # BUILD DOCUMENT CONTEXT
    docs_context_str = ""
    for idx, doc in enumerate(docs_text_list):
        filename = doc.get("filename", f"doc_{idx + 1}")
        t_fitz = doc.get("fitz", "")[:40000]
        t_plumber = doc.get("plumber", "")[:40000]

        docs_context_str += f"\n\n--- DOCUMENTO {idx + 1}: {filename} ---\n"
        docs_context_str += f"[CONTENIDO FITZ (Estructura Visual)]:\n{t_fitz}\n\n"
        docs_context_str += f"[CONTENIDO PLUMBER (Tabular/Lineal)]:\n{t_plumber}\n"
        docs_context_str += "--------------------------------------------------\n"

    descubrimiento_str = ""
    if info_descubrimiento and info_descubrimiento.get("campos"):
        descubrimiento_str = "\n\nInformacion de la Fase de Descubrimiento:\n"
        if info_descubrimiento.get("motor_recomendado"):
            descubrimiento_str += f"Nota: La IA de descubrimiento sugirio usar motor {info_descubrimiento.get('motor_recomendado')}.\n"
        descubrimiento_str += "Campos Detectados con Descripciones:\n"
        for campo_info in info_descubrimiento["campos"]:
            nombre = campo_info.get("campo", "N/A")
            desc = campo_info.get("descripcion", "Sin descripcion")
            ejemplo = campo_info.get("ejemplo", "Sin ejemplo")
            descubrimiento_str += f"  - {nombre}: {desc} (Ej: {ejemplo})\n"

    ejemplos_str = ""
    if valores_ejemplo:
        ejemplos_str = "\n\nValores Reales Extraidos en Fase de Prueba (Validacion):\n"
        for campo, valor in valores_ejemplo.items():
            if isinstance(valor, dict) and "valor" in valor:
                ejemplos_str += f"  - {campo}: '{valor['valor']}' (Pagina {valor.get('pagina', 'N/A')})\n"
            else:
                ejemplos_str += f"  - {campo}: '{valor}'\n"

    # --- ANCHOR-BASED LOGIC INJECTION ---
    field_defs_str = ""
    mode_instructions = ""

    if field_definitions:
        field_defs_str = "\n\n>>> DEFINICIONES ESTRICTAS DE CAMPOS (Inyectado):\n"
        for fd in field_definitions:
            # fd is dict: {name, description, example_value, is_optional}
            opt = "[OPCIONAL]" if fd.get("is_optional") else "[OBLIGATORIO]"
            ex = fd.get("example_value") or "N/A"
            desc = fd.get("description") or ""
            field_defs_str += (
                f"  - {fd['name']}: {opt} '{desc}'. (Anchor/Ejemplo: '{ex}')\n"
            )

        mode_instructions = (
            "\nESTRATEGIA 'ANCHOR-BASED' OBLIGATORIA:\n"
            "1. NO BUSQUES el valor literal del ejemplo (ej: 'INV-001') directamente. Ese valor cambia en Documento 2.\n"
            "2. DEBES BUSCAR EL PATRON/ETIQUETA que precede o rodea al valor (ej: 'Factura N:', 'Fecha:').\n"
            "3. Si un campo es [OBLIGATORIO] y no encuentras el anchor => devuelve None.\n"
            '4. Si un campo es [OPCIONAL] y no encuentras el anchor => devuelve cadena vacia "".\n'
            "5. Usa Hybrid Engine (fitz para texto, pdfplumber para tablas) segun Template.\n"
        )

    feedback_str = (
        f"\n\nINSTRUCCIONES DE ITERACION (Usuario):\n> {feedback_usuario}\n"
        if feedback_usuario
        else ""
    )
    auditoria_str = (
        f"\n\nRESULTADOS DE AUDITORIA PREVIA (Errores a corregir):\n{tabla_auditoria}\n"
        if tabla_auditoria
        else ""
    )

    combined_fitz_plumber = docs_context_str

    # We append the specific instructions to the generic system prompt or rely on prompt formatting
    # Assuming prompt_maestro has placeholders for this, or we append it to 'feedback_str' equivalent slot.
    # To avoid changing the DB Prompt Template yet, we inject this logic into 'feedback_str' or a new conceptual block
    # that is part of the 'user instructions' effectively.

    if mode_instructions:
        # Prepend to feedback to ensure high priority
        feedback_str = mode_instructions + field_defs_str + feedback_str

    prompt_maestro = system_prompt.format(
        campos_objetivo=campos_objetivo,
        texto_fitz=combined_fitz_plumber,
        texto_plumber="",
        descubrimiento_str=descubrimiento_str,
        ejemplos_str=ejemplos_str,
        feedback_str=feedback_str,
        auditoria_str=auditoria_str,
    )

    # Log the provider being used for transparency
    provider_info = f"{config_rol.get('provider', 'unknown')}/{config_rol.get('model_id', 'unknown')}"
    logger.debug("Llamando al modelo: %s", provider_info)

    resultado = await ejecutar_tarea(
        prompt_maestro, config_rol, script_origen="brain.extraction_strategies"
    )

    if "response" in resultado:
        return _limpiar_y_extraer_codigo_python(resultado["response"])
    else:
        # Include provider info in error message for better debugging
        error_msg = resultado.get("error", "Unknown error")
        raise RuntimeError(f"Error generando script con {provider_info}: {error_msg}")


def supervisar_codigo(
    script_codigo: str, campos_objetivo: List[str], config: Dict[str, Any]
) -> Dict[str, Any]:
    """Auditoria estatica basica (no usa LLM salvo si quisieramos, aqui es python puro)."""
    riesgos = []
    palabras_peligrosas = [
        "eval(",
        "exec(",
        "os.system",
        "subprocess",
        "shutil.rmtree",
        "__import__",
    ]
    for p in palabras_peligrosas:
        if p in script_codigo:
            riesgos.append(f"CRITICO: Uso de funcion peligrosa '{p}' detectada.")

    whitelist_libs = {
        "fitz",
        "pdfplumber",
        "pandas",
        "re",
        "json",
        "unicodedata",
        "datetime",
        "math",
        "collections",
        "typing",
        "io",
        "openpyxl",
    }

    try:
        imports = re.findall(
            r"^(?:import|from)\s+([a-zA-Z0-9_]+)", script_codigo, re.MULTILINE
        )
        librerias_detectadas = set(imports)
        librerias_desconocidas = librerias_detectadas - whitelist_libs
        if librerias_desconocidas:
            for lib in librerias_desconocidas:
                riesgos.append(
                    f"ADVERTENCIA: Libreria '{lib}' no esta en la lista blanca."
                )
    except Exception as e:
        riesgos.append(f"Error al analizar imports: {str(e)}")

    nivel_riesgo = (
        "Alto"
        if any("CRITICO" in r for r in riesgos)
        else ("Medio" if riesgos else "Bajo")
    )
    aprobado = len(riesgos) == 0
    confianza = 1.0 if aprobado else (0.5 if nivel_riesgo == "Medio" else 0.0)

    analisis = "Analisis Estatico de Seguridad:\n"
    if aprobado:
        analisis += (
            "Sin funciones peligrosas detectadas.\nTodas las librerias son conocidas."
        )
    else:
        analisis += "\n".join([f"- {r}" for r in riesgos])

    return {
        "aprobado": aprobado,
        "nivel_riesgo": nivel_riesgo,
        "analisis_seguridad": analisis,
        "puntuacion_confianza": confianza,
    }


async def generar_reporte_forense(
    referencia_ia: Dict,
    resultado_script: Any,
    config: Dict[str, Any],
    system_prompt: str,
) -> str:
    """
    Fase Audición: Genera un informe comparativo entre LLM y Script.

    Analiza las discrepancias entre la "verdad" de la IA y el resultado del
    código generado, detectando si hay fallos de lógica o falsos positivos.

    Args:
        referencia_ia: Datos extraídos por la IA (Ground Truth).
        resultado_script: Datos extraídos por el script generado.
        config: Configuración de IA para el análisis de discrepancias.
        system_prompt: Instrucciones para el auditor forense.

    Returns:
        str: Informe detallado con errores y sugerencias de corrección.
    """
    config_rol = (
        config.get("supervision", config)
        if isinstance(config, dict) and "supervision" in config
        else config
    )

    if not system_prompt:
        raise ValueError("El prompt de sistema es obligatorio para el Reporte Forense.")

    ref_json = json.dumps(referencia_ia, ensure_ascii=False)

    # Handle Result: Might be Dict (Single) or List (Multi)
    if isinstance(resultado_script, list):
        script_json = json.dumps(resultado_script, ensure_ascii=False, indent=2)
    else:
        script_json = json.dumps(resultado_script, ensure_ascii=False)

    prompt_forense = system_prompt.format(ref_json=ref_json, script_json=script_json)

    resultado = await ejecutar_tarea(
        prompt_forense, config_rol, script_origen="brain.extraction_strategies"
    )
    return resultado.get("response", "**Error al generar informe.**")


async def regenerar_script_iterativo(
    script_actual: str,
    reporte_forense: str,
    feedback_history: List[Dict],
    texto_documento: str,
    config: Dict[str, Any],
    system_prompt: str,
    campos_objetivo: List[str] = None,
) -> str:
    """Regenera script con feedback."""

    if not system_prompt:
        raise ValueError(
            "El prompt de sistema es obligatorio para la Regeneracion de Scripts."
        )

    if feedback_history and len(feedback_history) > 0:
        config_rol = (
            config.get("supervision", config)
            if isinstance(config, dict) and "supervision" in config
            else config
        )
        header_contexto = "ATENCION: TAREA DE RECUPERACION CRITICA. Rol: Staff Engineer. Corrige el codigo."
    else:
        config_rol = (
            config.get("logico_navegacion", config)
            if isinstance(config, dict) and "logico_navegacion" in config
            else config
        )
        header_contexto = "Rol: Senior Python Developer."

    # Inyectar objetivos en el contexto para asegurar que la IA no pierda el foco
    if campos_objetivo:
        header_contexto += f"\nCAMPOS OBJETIVO REQUERIDOS: {', '.join(campos_objetivo)}"

    historial_lines = []
    for i, item in enumerate(feedback_history):
        comentario = (
            item.get("comentario", str(item)) if isinstance(item, dict) else str(item)
        )
        historial_lines.append(f"Iteracion {i + 1}: {comentario}")
    historial_texto = "\n".join(historial_lines)

    prompt_reparacion = system_prompt.format(
        header_contexto=header_contexto,
        script_actual=script_actual,
        reporte_forense=reporte_forense,
        historial_texto=historial_texto,
        texto_documento=texto_documento[:40000],
        campos_objetivo=", ".join(campos_objetivo) if campos_objetivo else "",
    )

    # REFORZAMIENTO EXPLICITO DE OBJETIVOS (INJECTION)
    if campos_objetivo:
        seccion_objetivos = (
            f"\n\n>>> OBJETIVO INNEGOCIABLE: DEBES EXTRAER LOS SIGUIENTES CAMPOS:\n"
            f"{json.dumps(campos_objetivo, indent=2)}\n\n"
            f"INSTRUCCION ADICIONAL: Verifica que tu codigo final devuelva un diccionario con EXACTAMENTE estas claves. "
            f"Si el feedback dice que falta un campo, es tu PRIORIDAD NUMERO 1 arreglar su logica de extraccion."
        )
        # Insertar al principio o antes del script
        prompt_reparacion = seccion_objetivos + "\n\n" + prompt_reparacion

    resultado = await ejecutar_tarea(
        prompt_reparacion, config_rol, script_origen="brain.extraction_strategies"
    )
    if "response" in resultado:
        return _limpiar_y_extraer_codigo_python(resultado["response"])
    else:
        raise RuntimeError(f"Error regenerando script: {resultado.get('error')}")


def _limpiar_y_extraer_codigo_python(respuesta_raw: str) -> str:
    """Helper interno para limpiar codigo."""
    if not respuesta_raw:
        return ""
    codigo = respuesta_raw
    if "```python" in codigo:
        codigo = codigo.split("```python")[1].split("```")[0].strip()
    elif "```" in codigo:
        codigo = codigo.split("```")[1].split("```")[0].strip()
    return codigo


async def filtrar_datos_irrelevantes(
    datos_crudos: Dict[str, Any],
    definicion_usuario: str,
    config: Dict[str, Any],
    system_prompt: str,
) -> Dict[str, Any]:
    """
    Filtro de Ruido: Clasifica datos en 'relevantes' y 'otros_datos' segun la intencion del usuario.
    """
    # 1. Bypass si no hay definicion de usuario
    if not definicion_usuario or not definicion_usuario.strip():
        return datos_crudos

    # 2. Configurar Rol (Logico Navegacion recomendado)
    config_rol = config
    if isinstance(config, dict):
        if "logico_navegacion" in config:
            config_rol = config["logico_navegacion"]

    if not system_prompt:
        raise ValueError("El prompt de sistema es obligatorio para el Filtro de Datos.")

    # 3. Preparar entrada
    try:
        datos_str = json.dumps(datos_crudos, ensure_ascii=False)
    except Exception:
        datos_str = str(datos_crudos)

    # 4. Inyectar en Prompt
    prompt_completo = system_prompt.format(
        definicion_usuario=definicion_usuario,
        datos_crudos=datos_str[:50000],  # Truncate safety
    )

    # 5. Ejecutar LLM
    resultado = await ejecutar_tarea(
        prompt_completo, config_rol, script_origen="brain.extraction_strategies"
    )

    # 6. Parsear
    if "response" in resultado:
        return limpiar_respuesta_json(resultado["response"])
    else:
        # Fail-safe
        # `warning`: se devuelve el original, asi que el resultado es peor pero valido.
        logger.warning(
            "Fallo el filtro de ruido (nivel 2): %s. Se devuelve el original.",
            resultado.get("error"),
        )
        return datos_crudos


async def extraer_dato_desde_snippet(
    campo: str,
    snippet_texto: str,
    formato_esperado: str,
    config: Dict[str, Any],
    system_prompt: str,
) -> Dict[str, Any]:
    """
    Extraccion focalizada de un solo dato desde un snippet (Fallback).
    Expects prompt to support {campo}, {snippet_texto}, {formato}.
    Returns: { "valor": "...", "pagina": int|null, "confidence": float, "format_ok": bool }
    """
    if not system_prompt:
        raise ValueError("System prompt required for snippet extraction")

    # Override config to use provided role
    config_rol = config

    # We append a strong instruction for JSON structure if not present in prompt
    # Ideally this is in the prompt template, but we enforce it here to be safe
    instruction = (
        "\n\nOUTPUT FORMAT (STRICT JSON):\n"
        "{\n"
        '  "valor": "extracted value or empty string",\n'
        '  "confidence": 0.0 to 1.0,\n'
        '  "format_ok": true/false (matches expected type),\n'
        '  "pagina": null (or inferred page number if mentioned)\n'
        "}\n"
    )

    # Temporary prompt injection if the system prompt doesn't have it (User request C)
    prompt_snippet = (
        system_prompt.format(
            campo=campo, snippet_texto=snippet_texto[:4000], formato=formato_esperado
        )
        + instruction
    )

    resultado = await ejecutar_tarea(
        prompt_snippet, config_rol, script_origen="brain.strategies.fallback"
    )

    if "response" in resultado:
        return limpiar_respuesta_json(resultado["response"])
    else:
        return {"error": resultado.get("error")}


async def extract_field_from_snippet(
    field_name: str, snippet_text: str, expected_format: str, role: str, executor
) -> Dict[str, Any]:
    system = f"""Eres un extractor administrativo de datos.
Devuelve SOLO JSON valido sin texto adicional.
Devuelve el valor del campo solicitado si aparece en el fragmento, con confianza [0..1] y pagina si esta indicada.
Valida formato basico segun expected_format={expected_format} (date/money/iban/nif/text)."""

    user = f"""Campo objetivo: "{field_name}"

Fragmento (pares clave-valor y notas de pagina):
{snippet_text[:8000]}

Formato EXACTO:
{{
"valor": "...",
"pagina": 3,
"confidence": 0.92,
"format_ok": true
}}

Reglas:
- Si hay varios candidatos, elige el mas consistente con el campo (p.ej., para "IBAN" un formato IBAN).
- 'pagina' puede ser null si no esta indicada explicitamente (p.X).
- Si no se encuentra, devuelve:
{{"valor":"","pagina":null,"confidence":0.0,"format_ok":false}}
"""
    raw = await executor.run(role=role, system=system, user=user)
    try:
        import json
        import re

        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        # Validacion ligera
        ok = bool(data.get("valor"))
        val = str(data.get("valor", ""))
        fmt = (expected_format or "text").lower()

        if fmt == "iban" and not re.search(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,}\b", val):
            ok = False
        if fmt == "nif" and not re.search(r"\b[XYZ]?\d{7}[A-Z]\b", val, re.I):
            ok = False
        if fmt == "date" and not re.search(
            r"\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b", val
        ):
            ok = False
        if fmt in ("money", "importe") and not re.search(
            r"\d{1,3}(\.\d{3})*(,\d{2})", val
        ):
            ok = False

        data["format_ok"] = bool(ok)
        ph = data.get("pagina")
        data["pagina"] = int(ph) if isinstance(ph, (int, float)) else None
        try:
            data["confidence"] = float(data.get("confidence", 0.0))
        except Exception:
            data["confidence"] = 0.0

        return data
    except Exception:
        return {"valor": "", "pagina": None, "confidence": 0.0, "format_ok": False}
