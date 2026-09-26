"""
LLM Gateway - Central interface for AI model interactions.

This module provides:
- Unified interface to multiple LLM providers (Google, OpenRouter, Ollama)
- Token logging for billing
- Retry logic for transient failures
- JSON response cleaning utilities
"""

import json
import logging
import re
import openai
from google import genai
from typing import Dict, Any

# Issue #18 — la pasarela habla en el camino de una peticion, y justo cuando algo va mal. Era
# el peor sitio para imprimir: el diagnostico de red que hay aqui abajo es exactamente lo que
# se necesita leer despues de una caida, y sin nivel ni marca de tiempo no se puede correlacionar
# con nada.
logger = logging.getLogger(__name__)

# --- HELPER FUNCTIONS ---


def registrar_log_tokens(
    proveedor, modelo, tokens_enviados, tokens_recibidos, script_origen="gui.py"
):
    """Registra el uso de tokens en base de datos (wrapper async)."""
    try:
        import asyncio
        from server.app.services.token_service import log_token_usage

        # Create task in the running loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                log_token_usage(
                    script_source=script_origen,
                    provider=proveedor,
                    model=modelo,
                    input_tokens=tokens_enviados,
                    output_tokens=tokens_recibidos,
                )
            )
        except RuntimeError:
            # No running loop (e.g. script usage), fallback to sync DB or skip
            # For now just print error or skip as this is mainly for GUI app
            logger.warning(
                "Sin bucle de eventos: no se registra el consumo de tokens de esta llamada"
            )

    except Exception:
        logger.exception("Fallo el registro del consumo de tokens")


def limpiar_respuesta_json(respuesta_raw: str) -> Dict[str, Any]:
    """Centraliza la limpieza y el parseo de JSON."""
    if not respuesta_raw:
        return {}

    patron_bloque = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(patron_bloque, respuesta_raw)

    if match:
        contenido = match.group(1).strip()
    else:
        # Intento heuristico de encontrar { ... } o [ ... ]
        inicio_json = re.search(r"[\{\[]", respuesta_raw)
        if inicio_json:
            inicio = inicio_json.start()
            cierre = "}" if respuesta_raw[inicio] == "{" else "]"
            fin = respuesta_raw.rfind(cierre)
            if fin != -1:
                contenido = respuesta_raw[inicio : fin + 1].strip()
            else:
                contenido = respuesta_raw[inicio:].strip()
        else:
            contenido = respuesta_raw.strip()

    try:
        return json.loads(contenido)
    except json.JSONDecodeError:
        try:
            # Intento desesperado: quitar saltos de linea
            contenido_alt = contenido.replace("\n", " ").replace("\r", "")
            return json.loads(contenido_alt)
        except json.JSONDecodeError:
            # Retorna dic vacio o error segun prefieras.
            # Originalmente lanzaba ValueError. Mantengamos compatibilidad.
            return {}


async def ejecutar_tarea(
    prompt: str, config_rol: Dict[str, Any], script_origen: str = "core.llm"
) -> Dict[str, Any]:
    """
    Ejecuta una tarea usando el LLM configurado (Async).
    """
    from server.app.services.api_key_service import get_api_key
    from server.app.services.token_service import log_token_usage

    if not config_rol:
        return {"error": "No hay configuracion asignada para el rol"}

    # Soporte para formato antiguo (dict) o nuevo (objeto SQLModel si se pasara, pero aqui asumimos dict)
    if hasattr(config_rol, "provider"):
        proveedor = config_rol.provider
    else:
        proveedor = config_rol.get("proveedor") or config_rol.get("provider")

    if hasattr(config_rol, "model_id"):
        modelo = config_rol.model_id
    else:
        modelo = config_rol.get("modelo") or config_rol.get("model_id")

    if not proveedor or not modelo:
        return {"error": "Configuracion incompleta"}

    tokens_enviados = 0
    tokens_recibidos = 0

    max_retries = 3
    backoff_factor = 2  # Seconds

    import asyncio

    for attempt in range(max_retries):
        try:
            if proveedor.lower() == "google":
                api_key = await get_api_key("google")
                if not api_key:
                    return {"error": "API Key de Google no encontrada en BD"}

                client = genai.Client(api_key=api_key)

                # Offload de la llamada bloqueante a un hilo (sin acoplar el backend a UI)
                def _google_call():
                    # Check if stream is needed or plain generate_content
                    # Original code used generate_content_stream but concatenated immediately.
                    # generate_content might be simpler if we don't actually stream to UI here.
                    # But sticking to original logic:
                    response_stream = client.models.generate_content_stream(
                        model=modelo, contents=prompt
                    )
                    txt = ""
                    final = None
                    for chunk in response_stream:
                        if chunk.text:
                            txt += chunk.text
                        final = chunk
                    return txt, final

                response_text, final_response = await asyncio.to_thread(_google_call)

                if final_response and final_response.usage_metadata:
                    tokens_enviados = final_response.usage_metadata.prompt_token_count
                    tokens_recibidos = (
                        final_response.usage_metadata.candidates_token_count
                    )

                await log_token_usage(
                    script_origen, proveedor, modelo, tokens_enviados, tokens_recibidos
                )
                return {"response": response_text}

            elif proveedor.lower() == "openrouter":
                api_key = await get_api_key("openrouter")
                if not api_key:
                    return {"error": "API Key de OpenRouter no encontrada en BD"}

                client = openai.AsyncOpenAI(
                    api_key=api_key, base_url="https://openrouter.ai/api/v1"
                )
                response = await client.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False,
                )

                response_text = response.choices[0].message.content
                if response.usage:
                    tokens_enviados = response.usage.prompt_tokens
                    tokens_recibidos = response.usage.completion_tokens

                await log_token_usage(
                    script_origen, proveedor, modelo, tokens_enviados, tokens_recibidos
                )
                return {"response": response_text}

            else:
                return {"error": f"Proveedor no soportado: {proveedor}"}

        except Exception as e:
            error_str = str(e)
            logger.warning(
                "Error con %s (intento %d de %d): %s",
                proveedor,
                attempt + 1,
                max_retries,
                error_str,
            )

            # Special handling for DNS / Connectivity issues
            if "getaddrinfo" in error_str or "connection" in error_str.lower():
                logger.warning(
                    "Error de red detectado; se comprueba la resolucion de nombres"
                )
                import socket

                host_to_check = (
                    "generativelanguage.googleapis.com"
                    if proveedor.lower() == "google"
                    else "openrouter.ai"
                )
                try:
                    addr = socket.gethostbyname(host_to_check)
                    logger.info(
                        "Diagnostico: %s resuelve a %s, el DNS responde", host_to_check, addr
                    )
                except Exception as dns_e:
                    logger.error(
                        "Diagnostico: no se resuelve %s; problema de red confirmado: %s",
                        host_to_check,
                        dns_e,
                    )

            # Check if retryable (Internal Error, 500, 503, Gateway Timeout, or transient DNS issue)
            retry_reason = None
            if (
                "500" in error_str
                or "503" in error_str
                or "Internal" in error_str.upper()
            ):
                retry_reason = "Server Error"
            elif "getaddrinfo" in error_str:
                retry_reason = "Transient DNS Failure"

            if retry_reason:
                if attempt < max_retries - 1:
                    sleep_time = backoff_factor * (2**attempt)
                    logger.warning(
                        "%s; se reintenta en %s segundos", retry_reason, sleep_time
                    )
                    await asyncio.sleep(sleep_time)
                    continue

            # Non-retryable or max retries reached
            return {"error": f"Error con {proveedor}: {e}"}
