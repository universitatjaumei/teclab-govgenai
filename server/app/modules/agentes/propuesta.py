"""La propuesta del prompt de un agente a partir de su finalidad (#213).

Deploy: edge.

Escribir un buen prompt es lo que más cuesta a quien publica. Aquí se compone lo que se le pide al
modelo: **propone, no publica**. La propuesta va al formulario, la unidad la edita y decide.

**El meta-prompt sabe lo que la plataforma añade siempre** al entregar el prompt —la pregunta, los
enlaces y la instrucción de abstención, y la frase del adjunto si el agente lo espera—, para que
la propuesta no lo repita ni lo contradiga. Y le prohíbe inventar normas, plazos o importes: lo
que el agente sepa tiene que salir de los documentos.

**La descripción no se anonimiza**, como no se anonimiza lo que se escribe en el copiloto ni la
petición de una plantilla: es configuración que redacta el personal, no datos de nadie, y el
anonimizador desfiguraría el nombre de la unidad.
"""
from __future__ import annotations

import re
from typing import Literal

Lengua = Literal["es", "ca", "en"]

#: Versionado, como el prompt de resumen: la respuesta lo dice, y con él se sabe con qué
#: instrucciones se hizo una propuesta.
VERSION_META_PROMPT = "propuesta-prompt-v1"

_NOMBRE_DE_LA_LENGUA = {"es": "castellano", "ca": "valenciano", "en": "inglés"}


def meta_prompt(lengua: Lengua, *, espera_adjunto: bool) -> str:
    """Las instrucciones para quien redacta. Fijas y en castellano; el prompt sale en `lengua`."""
    adjunto = (
        " Además, quien consulta adjuntará un documento propio, y la plataforma ya indica que se "
        "analice usando como criterio los documentos enlazados: el prompt tiene que decir qué "
        "buscar en ese documento y cómo presentar el análisis."
        if espera_adjunto
        else ""
    )
    return (
        "Redactas el prompt de sistema de un «agente de unidad» de una administración pública. El "
        "personal lo usa a través del asistente general de la organización: la plataforma entrega "
        "a ese asistente el prompt que tú redactes y, por su cuenta, añade siempre la pregunta de "
        "quien consulta, los enlaces a los documentos pertinentes de la unidad y una instrucción de "
        "abstención (si no puede abrir los documentos, que lo diga y no responda a partir de otra "
        f"cosa).{adjunto}\n\n"
        "Redacta sólo el prompt: el papel del agente, para quién trabaja, qué debe hacer y qué no, "
        "el tono y la forma de la respuesta. No incluyas la pregunta, no listes documentos ni "
        "enlaces, no repitas la instrucción de abstención y no inventes normas, plazos ni importes: "
        "lo que el agente sepa saldrá de los documentos. Entre 120 y 350 palabras, en segunda "
        f"persona («Eres…»). Escribe el prompt en {_NOMBRE_DE_LA_LENGUA[lengua]}. Responde "
        "únicamente con el prompt, sin explicaciones, títulos ni comillas."
    )


def mensajes(
    *,
    descripcion: str,
    nombre: str | None,
    unidad: str | None,
    finalidad: str | None,
    colectivo: str | None,
    grupos: list[str],
    espera_adjunto: bool,
    lengua: Lengua,
) -> list[dict[str, str]]:
    """El sistema con las instrucciones y el usuario con lo que la unidad ha dicho y declarado."""
    lineas = [f"Lo que la unidad quiere que haga el agente:\n{descripcion.strip()}"]
    if nombre:
        lineas.append(f"Nombre del agente: {nombre.strip()}")
    if unidad:
        lineas.append(f"Unidad que lo publica: {unidad.strip()}")
    if finalidad:
        lineas.append(f"Finalidad declarada: {finalidad.strip()}")
    if colectivo == "grupos" and grupos:
        lineas.append(f"Quién lo usa: los grupos {', '.join(grupos)}")
    elif colectivo:
        lineas.append("Quién lo usa: toda la organización")
    lineas.append(f"Quien consulta adjunta un documento propio: {'sí' if espera_adjunto else 'no'}")
    return [
        {"role": "system", "content": meta_prompt(lengua, espera_adjunto=espera_adjunto)},
        {"role": "user", "content": "\n\n".join(lineas)},
    ]


_VALLA = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def limpiar(texto: str) -> str:
    """Quita lo que los modelos ponen alrededor aunque se les pida que no: vallas y comillas."""
    limpio = texto.strip()
    valla = _VALLA.match(limpio)
    if valla:
        limpio = valla.group(1).strip()
    if len(limpio) >= 2 and limpio[0] == limpio[-1] and limpio[0] in "\"'«":
        limpio = limpio[1:-1].strip()
    if limpio.startswith("«") and limpio.endswith("»"):
        limpio = limpio[1:-1].strip()
    return limpio
