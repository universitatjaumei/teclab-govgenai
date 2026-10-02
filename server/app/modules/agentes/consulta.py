"""El prompt compuesto de una consulta a un agente de unidad (#175).

Deploy: edge.

Lo que se entrega es **el prompt del agente, la pregunta y los enlaces**, nunca el contenido de
los documentos: el asistente general los abre con la identidad de quien pregunta, y el almacén
decide si puede. Son dos puertas independientes, y la plataforma no custodia copias.

**La instrucción de abstención va siempre, y literal.** Si un enlace no se puede abrir, el
asistente lo dice en vez de contestar de memoria: el mismo instinto que el contrato de cita de la
plataforma —sin fundamento, se calla— y lo que convierte un fallo silencioso en uno que se lee.

Las instrucciones fijas van en la lengua de quien pregunta; el prompt del agente, en la que lo
escribió su unidad.
"""
from __future__ import annotations

from typing import Literal

from server.app.modules.agentes.indice import FichaSeleccionada

Lengua = Literal["es", "ca", "en"]

_TEXTOS: dict[str, dict[str, str]] = {
    "es": {
        "pregunta": "Pregunta",
        "documentos": "Responde sólo a partir de estos documentos:",
        "documentos_con_adjunto": (
            "Quien pregunta te adjuntará un documento: analízalo usando como criterio estos "
            "documentos:"
        ),
        "abstencion_con_adjunto": (
            "Si no puedes abrir los documentos enlazados, o no te ha llegado el documento "
            "adjunto, dilo y no respondas a partir de otra cosa."
        ),
        "pendiente": "pendiente de revisión",
        "ninguno": (
            "No se ha encontrado ningún documento pertinente en el índice de este agente: dilo y "
            "no respondas a partir de otra cosa."
        ),
        "abstencion": (
            "Si no puedes abrir los documentos enlazados, dilo y no respondas a partir de otra cosa."
        ),
    },
    "ca": {
        "pregunta": "Pregunta",
        "documentos": "Respon només a partir d'aquests documents:",
        "documentos_con_adjunto": (
            "Qui pregunta t'adjuntarà un document: analitza'l fent servir com a criteri aquests "
            "documents:"
        ),
        "abstencion_con_adjunto": (
            "Si no pots obrir els documents enllaçats, o no t'ha arribat el document adjunt, "
            "digues-ho i no respongues a partir d'una altra cosa."
        ),
        "pendiente": "pendent de revisió",
        "ninguno": (
            "No s'ha trobat cap document pertinent a l'índex d'aquest agent: digues-ho i no "
            "respongues a partir d'una altra cosa."
        ),
        "abstencion": (
            "Si no pots obrir els documents enllaçats, digues-ho i no respongues a partir d'una "
            "altra cosa."
        ),
    },
    "en": {
        "pregunta": "Question",
        "documentos": "Answer only from these documents:",
        "documentos_con_adjunto": (
            "The person asking will attach a document: analyse it using these documents as the "
            "criteria:"
        ),
        "abstencion_con_adjunto": (
            "If you cannot open the linked documents, or the attached document has not reached "
            "you, say so and do not answer from anything else."
        ),
        "pendiente": "pending review",
        "ninguno": (
            "No relevant document was found in this agent's index: say so and do not answer from "
            "anything else."
        ),
        "abstencion": (
            "If you cannot open the linked documents, say so and do not answer from anything else."
        ),
    },
}


def componer(
    prompt_del_agente: str,
    consulta: str,
    documentos: list[FichaSeleccionada],
    lengua: Lengua,
    *,
    espera_adjunto: bool = False,
) -> str:
    """El texto que se pega en el asistente general. Kilobytes, también a mano.

    Con `espera_adjunto`, los enlaces pasan de ser la única fuente a ser **el criterio** con el
    que se analiza lo que adjunte quien pregunta, y la abstención cubre también el adjunto que no
    llega: si la persona se olvida de adjuntarlo, el asistente lo dice.
    """
    t = _TEXTOS[lengua]
    partes = [prompt_del_agente.strip(), f"{t['pregunta']}: {consulta.strip()}"]
    if documentos:
        lineas = [t["documentos_con_adjunto" if espera_adjunto else "documentos"]]
        for n, d in enumerate(documentos, start=1):
            marca = f" ({t['pendiente']})" if d.revision_vencida else ""
            lineas.append(f"{n}. {d.titulo} — {d.url}{marca}")
        partes.append("\n".join(lineas))
    else:
        partes.append(t["ninguno"])
    partes.append(t["abstencion_con_adjunto" if espera_adjunto else "abstencion"])
    return "\n\n".join(partes)
