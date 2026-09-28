"""El evento de actividad IA: qué se registra de un uso de IA ocurrido fuera de la plataforma.

Deploy: edge

**Registro de gobernanza, no trazado técnico.** Sirve a la conservación de registros del AI Act y
al registro de actividades de tratamiento del RGPD: quién usó qué agente, con qué finalidad y sobre
qué categorías de datos. El detalle token a token de las conversaciones internas ya lo cubre la
observabilidad de la plataforma y no se reconstruye aquí.

Lo registran herramientas de terceros —asistentes de escritorio, agentes de código, integraciones
propias— para que una organización pueda responder «qué IA se usó aquí» sin depender de que cada
herramienta lo cuente a su manera.

**Metadatos sí, payloads no.** No hay ningún campo de contenido, y `extra="forbid"` rechaza los que
lleguen sin declarar en vez de ignorarlos: aceptado en silencio, un campo de contenido haría creer
a quien integra que se guardó algo que no se guardó, y quien audite el registro no sabría si están
todos los datos. Si un caso exige evidencia de lo que se procesó, va `payload_hash` y nunca el
texto. La razón es que el registro existe para dar cuenta del tratamiento de datos personales: si
además los contuviera, sería el problema en vez de la respuesta.

Los nombres de campo son propios y mapeables a las convenciones semánticas OTel GenAI; el mapeo
campo a campo está en `docs/REGISTRO_ACTIVIDAD_IA.md`. Adoptar el estándar entero arrastraría
atributos de observabilidad que aquí no aplican.
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

#: SHA-256 en hexadecimal minúscula. Se valida la forma porque un hash mal formado no sirve para
#: cotejar nada, y el error tiene que salir al registrar y no el día de la auditoría.
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: Dónde está explicado todo el contrato, para que quien se estrelle no tenga que preguntar.
_DOCUMENTO = "docs/REGISTRO_ACTIVIDAD_IA.md"

#: Nombres con los que un integrador intenta mandar el contenido. No es una lista de prohibidos
#: —`extra="forbid"` ya rechaza cualquier campo no declarado—: es la lista de los que reciben la
#: explicación de la regla en vez del mensaje genérico, porque son los que se mandan de buena fe.
_NOMBRES_DE_CONTENIDO = frozenset(
    {
        "payload",
        "content",
        "contenido",
        "prompt",
        "mensaje",
        "message",
        "texto",
        "text",
        "respuesta",
        "response",
        "completion",
        "input",
        "output",
    }
)


class ActividadIAEvent(BaseModel):
    """Un uso de IA declarado por una herramienta externa.

    La organización **no viaja en el evento**: se deriva del token que autentica la petición. Un
    agente externo no elige en nombre de qué organización registra, igual que no elige qué datos
    puede leer.
    """

    model_config = {"extra": "forbid"}

    #: Cuándo ocurrió el uso, según quien lo declara. Exige zona horaria: sin ella, dos
    #: herramientas en husos distintos producen un registro que no se puede ordenar.
    ocurrido_en: datetime

    #: Identificador **opaco** de la persona en la herramienta externa. Opaco a propósito: para
    #: dar cuenta de un tratamiento basta poder correlacionar, no identificar desde el registro.
    actor: str = Field(min_length=1, max_length=255)

    #: La herramienta: `claude-cowork`, `copilot`, `cursor`… Texto libre porque el catálogo de
    #: herramientas cambia sin que este código tenga nada que decir.
    herramienta: str = Field(min_length=1, max_length=100)

    #: El agente o bot concreto dentro de esa herramienta, cuando lo hay.
    agente: str | None = Field(default=None, max_length=255)

    #: La finalidad declarada, en una línea. Es el único campo de texto libre, y es el que da
    #: sentido al registro: sin finalidad, saber que alguien usó una IA no informa de nada.
    finalidad: str = Field(min_length=1, max_length=500)

    modelo_usado: str | None = Field(default=None, max_length=100)

    #: Categorías de datos declaradas. **Lista libre, sin `Enum`**: es vocabulario, no estructura,
    #: y vale la misma regla que para el vocabulario del corpus — si fuera enumeración cerrada,
    #: una categoría nueva exigiría migración y despliegue del núcleo.
    categorias_datos: list[str] = Field(default_factory=list)

    #: SHA-256 del contenido procesado, si el caso exige poder cotejarlo. **Nunca el contenido.**
    payload_hash: str | None = None

    #: AUT.5 — SHA-256 del **programa** que se ejecutó, cuando está registrado en el catálogo
    #: como función de origen externo (AUT.3). Es `HubFuncionVersion.code_sha256`, y cierra el
    #: circuito: el catálogo dice qué cuadernos existen y el registro dice cuándo corrieron.
    #:
    #: **Campo propio y no `payload_hash`.** Aquél significa «el contenido que se procesó», y
    #: darle un segundo significado dejaría el único campo que sirve para cotejar un tratamiento
    #: concreto sin poder leerse. Un campo nuevo cuesta una migración; uno ambiguo cuesta una
    #: auditoría.
    #:
    #: Si no casa con ninguna versión del catálogo, tampoco pasa nada y es información: consta
    #: que se ejecutó algo que no está registrado.
    funcion_sha256: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _explica_lo_que_sobra(cls, datos):
        """Convierte «Extra inputs are not permitted» en algo que se pueda actuar (REG.9).

        `extra="forbid"` ya hace cumplir la regla; lo que no hace es decir **por qué**. Y la
        diferencia tiene consecuencias: quien integra lee «este campo no está permitido» y saca
        la conclusión razonable de que al esquema le falta algo, así que pide que se añada. La
        conversación de explicar que el registro no puede convertirse en un segundo sitio donde
        viven los datos personales acaba teniéndose igual, sólo que a posteriori y por un canal
        lento — cuando cabía aquí, gratis, en el momento en que alguien está mirando.

        Se distinguen dos casos porque son dos malentendidos distintos: mandar el contenido es
        chocar con la regla del bloque, y mandar `organizacion_id` es creer que se elige algo que
        sale del token. Para cualquier otro extra, el mensaje genérico con el puntero: no vale la
        pena adivinar la intención de un campo que nadie ha visto todavía.

        Va en `mode="before"` para llegar antes que el rechazo de Pydantic, y sólo actúa si el
        campo no está declarado — así añadir un campo al contrato no lo convierte en un error por
        parecerse a uno de estos nombres.
        """
        if not isinstance(datos, dict):
            return datos

        declarados = set(cls.model_fields)
        sobran = [nombre for nombre in datos if nombre not in declarados]
        if not sobran:
            return datos

        de_contenido = [n for n in sobran if n.lower() in _NOMBRES_DE_CONTENIDO]
        if de_contenido:
            raise ValueError(
                f"El registro guarda **metadatos** de gobernanza, nunca el contenido, así que "
                f"{', '.join(f'`{n}`' for n in de_contenido)} no cabe en el evento: si lo "
                f"aceptara, el registro sería un segundo sitio donde viven los datos personales "
                f"que existe para inventariar. Si necesitas dejar prueba de qué texto se "
                f"procesó, manda su SHA-256 en `payload_hash`. Contrato completo en "
                f"{_DOCUMENTO}."
            )

        if "organizacion_id" in sobran:
            raise ValueError(
                "`organizacion_id` no se manda: sale del dueño del token que autentica la "
                "petición. Si viajara en el evento, un token de una organización podría "
                f"escribir en el registro de otra. Contrato completo en {_DOCUMENTO}."
            )

        raise ValueError(
            f"El evento no admite {', '.join(f'`{n}`' for n in sobran)}: sólo los campos que "
            f"declara el contrato, para que quien audite el registro sepa qué hay en él. "
            f"Contrato completo en {_DOCUMENTO}."
        )

    @field_validator("ocurrido_en")
    @classmethod
    def _con_zona_horaria(cls, valor: datetime) -> datetime:
        if valor.tzinfo is None or valor.utcoffset() is None:
            raise ValueError(
                "`ocurrido_en` tiene que llevar zona horaria: sin ella, dos herramientas en "
                "husos distintos producen un registro que no se puede ordenar."
            )
        return valor

    @field_validator("payload_hash", "funcion_sha256")
    @classmethod
    def _es_un_sha256(cls, valor: str | None, info) -> str | None:
        """La forma de los dos hashes, con la misma regla y por el mismo motivo.

        La minúscula no es estética: `code_sha256` se guarda así, y dos formas del mismo hash no
        se cruzan solas. Un hash que no va a casar con nada es mejor saberlo al registrar que en
        la auditoría, cuando ya no se puede rehacer.
        """
        if valor is not None and not _SHA256.match(valor):
            raise ValueError(
                f"`{info.field_name}` tiene que ser un SHA-256 en hexadecimal minúscula (64 "
                "caracteres). Un hash mal formado no sirve para cotejar nada."
            )
        return valor
