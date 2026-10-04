"""Qué se guarda de las conversaciones con un agente de unidad, y con qué vocabulario (#216).

Deploy: edge.

**Decisión del usuario (2026-10-03)**: son conversaciones de trabajo sobre documentos de la
organización, quien las tiene sabe que se registran, y prevalece la calidad de las respuestas.
Como las conversaciones de los chatbots.

Los motivos de un informe los sirve la plataforma, con su etiqueta en cada lengua: la extensión y
el panel los pintan, no los conocen. Son código y no tabla porque los consume la pantalla de
calidad (#217), que tiene que saber qué significa cada uno para decir dónde está el fallo.
"""
from __future__ import annotations

MODOS = ("validacion", "incidencias")

#: Por qué no hay respuesta capturada: no se envió, no terminó en el plazo, un selector falló, o se
#: copió para pegarlo a mano y la extensión no puede leer dónde se pegó.
SIN_CAPTURA = ("sin_respuesta", "sin_terminar", "selector", "copiado")

#: Los motivos de un informe, en el orden en que se ofrecen. Cada uno apunta a un sitio distinto:
#: `no_abre` y `desactualizado` al índice o al almacén, `inventa` y `no_responde` al prompt o al
#: modelo, `incompleta` a la selección.
MOTIVOS: dict[str, dict[str, str]] = {
    "no_abre": {
        "es": "No pudo abrir los documentos",
        "ca": "No va poder obrir els documents",
        "en": "It could not open the documents",
    },
    "desactualizado": {
        "es": "Información desactualizada",
        "ca": "Informació desactualitzada",
        "en": "Out-of-date information",
    },
    "inventa": {
        "es": "Se inventa cosas",
        "ca": "S'inventa coses",
        "en": "It makes things up",
    },
    "incompleta": {
        "es": "Respuesta incompleta",
        "ca": "Resposta incompleta",
        "en": "Incomplete answer",
    },
    "no_responde": {
        "es": "No responde a lo que pregunté",
        "ca": "No respon al que vaig preguntar",
        "en": "It does not answer what I asked",
    },
    "otro": {
        "es": "Otro motivo",
        "ca": "Un altre motiu",
        "en": "Another reason",
    },
}


#: #217 — dónde mirar primero según el motivo del informe. **Una pista, no un diagnóstico**: quien
#: revisa tiene la pregunta, los documentos ofrecidos y la respuesta, y decide. `almacen` es el
#: permiso o el enlace; `indice`, la carpeta o el resumen; `prompt`, las instrucciones del agente;
#: `seleccion`, el presupuesto de documentos o los datos de la consulta. «Otro» no apunta a nada.
PISTAS: dict[str, str] = {
    "no_abre": "almacen",
    "desactualizado": "indice",
    "inventa": "prompt",
    "incompleta": "seleccion",
    "no_responde": "prompt",
}
