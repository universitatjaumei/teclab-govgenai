"""El manifiesto de una ejecución hecha **fuera** de la plataforma (AUT.6, issue #116).

Deploy: edge — describe un tratamiento de datos de la organización.

Es el candidato §4.2 de `docs/GOVERNANCA_PER_API.md`, y el paso que va del **evento** a la
**evidencia**:

- El evento de actividad (REG.2, AUT.5) dice «quién, qué, cuándo, con qué finalidad».
- El manifiesto dice **qué pasó dentro de esa ejecución**: qué modelo, qué versión de prompt, qué
  fuentes se citaron, quién aprobó qué y con qué salida.

Una aplicación construida fuera que genere informes con IA deposita el manifiesto de cada
generación, y el panel los lee junto a los de la plataforma **distinguiendo el origen**: un
manifiesto declarado por un tercero no tiene la misma autoridad que uno que la plataforma produjo
ella misma, y confundirlos sería el problema que este registro existe para evitar.

**Y sin contenido.** El `DraftingRunManifest` propio guarda citas con `excerpt` —un trozo del
documento—, y eso aquí no puede entrar: un depósito abierto por API que admitiera extractos sería
un segundo sitio donde viven los datos personales de la organización, creado justo por la
herramienta que existe para llevar la cuenta de los riesgos. Es la misma regla del evento de
actividad, y se hace cumplir igual: `extra="forbid"` más un mensaje que dice **por qué** en vez
de «Extra inputs are not permitted», porque quien lee eso concluye razonablemente que al esquema
le falta un campo y pide que se añada.

**Un cuaderno determinista no necesita manifiesto**: le basta el evento. Esto añade evidencia
cuando hubo un modelo de por medio.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

#: SHA-256 en hexadecimal minúscula. La minúscula no es estética: es la forma en que se guardan
#: los hashes del catálogo, y dos formas del mismo hash no se cruzan solas.
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: Nombres que llegan de buena fe cuando alguien intenta mandar el contenido. Reciben un mensaje
#: que explica la regla; cualquier otro extra recibe el genérico con el puntero. No vale la pena
#: adivinar la intención de un campo que nadie ha visto todavía.
_SUENAN_A_CONTENIDO = frozenset(
    {
        "documento",
        "texto",
        "contenido",
        "content",
        "payload",
        "salida",
        "output",
        "respuesta",
        "prompt",
        "mensaje",
    }
)


#: Lo que alguien manda de buena fe dentro de una cita cuando quiere adjuntar el trozo citado.
_EXTRACTOS = frozenset({"excerpt", "extracto", "fragmento", "cita", "snippet"})


def _explica_el_contenido(datos, declarados: set[str], sospechosos: frozenset[str]) -> None:
    """Levanta con el porqué si entre los extras hay algo que parece contenido.

    **Se aplica también dentro de la cita**, y no sólo en la raíz, porque es justo ahí donde
    llega el intento razonable: el manifiesto propio de la plataforma guarda `excerpt`, así que
    quien conoce aquel contrato lo manda aquí y recibe «Extra inputs are not permitted». De ese
    mensaje se concluye que al esquema le falta un campo, y la conversación de explicar la regla
    acaba teniéndose igual, sólo que a posteriori.
    """
    if not isinstance(datos, dict):
        return
    de_contenido = [c for c in datos if c not in declarados and c.lower() in sospechosos]
    if not de_contenido:
        return
    raise ValueError(
        f"{', '.join(sorted(de_contenido))}: este manifiesto guarda **metadatos**, nunca el "
        "contenido. Un depósito que admitiera el texto sería un segundo sitio donde viven los "
        "datos personales de la organización — uno más que inventariar, proteger y borrar, "
        "creado por la herramienta que existe para llevar la cuenta de los riesgos. Si hace "
        "falta poder cotejar la salida, va su SHA-256 en `hash_de_la_salida`."
    )


class CitaDeclarada(BaseModel):
    """Una fuente citada, **por referencia**.

    Sin `excerpt`, al contrario que la `Citation` del manifiesto propio: aquélla vive dentro de
    la plataforma, sobre documentos que la plataforma ya tiene; ésta llega por API desde fuera.
    """

    model_config = {"extra": "forbid"}

    #: URL o identificador estable del documento citado.
    fuente: str = Field(min_length=1, max_length=1000)
    pagina: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _sin_extracto(cls, datos):
        _explica_el_contenido(datos, set(cls.model_fields), _EXTRACTOS)
        return datos


class AprobacionDeclarada(BaseModel):
    """Quién aprobó qué, y cuándo. Es lo que distingue supervisión instrumentada de declarada."""

    model_config = {"extra": "forbid"}

    #: Identificador **opaco** de la persona, como en el evento de actividad: para dar cuenta de
    #: una supervisión basta poder correlacionar, no identificar desde el registro.
    actor: str = Field(min_length=1, max_length=255)
    aprobado_en: datetime
    #: Qué se aprobó, en una línea: «el bloque de valoración», «el informe entero».
    que_aprobo: str = Field(min_length=1, max_length=255)


class ManifiestoExterno(BaseModel):
    """La evidencia de una generación hecha fuera. Metadatos; nunca contenido."""

    model_config = {"extra": "forbid"}

    #: Cuándo ocurrió la ejecución, según quien la declara. Con zona horaria, por lo mismo que el
    #: evento de actividad: un instante sin zona no es un instante.
    ocurrido_en: datetime

    #: Qué aplicación la generó: `informes-uadti`, `revisor-de-pliegos`… Texto libre, porque el
    #: catálogo de aplicaciones de una institución cambia sin que este código tenga nada que decir.
    aplicacion: str = Field(min_length=1, max_length=100)

    #: El identificador que esa aplicación le da a su propia ejecución. Sirve para conciliar los
    #: dos registros sin que la plataforma tenga que inventar una correspondencia.
    referencia_externa: str | None = Field(default=None, max_length=255)

    finalidad: str = Field(min_length=1, max_length=500)

    modelo_usado: str | None = Field(default=None, max_length=100)
    versiones_de_prompt: list[str] = Field(default_factory=list)

    citas: list[CitaDeclarada] = Field(default_factory=list)
    aprobaciones: list[AprobacionDeclarada] = Field(default_factory=list)

    #: SHA-256 de la salida generada. Es lo que permite demostrar meses después que un documento
    #: concreto es el que salió de esta ejecución, **sin guardar el documento**.
    hash_de_la_salida: str | None = None

    #: AUT.5/AUT.3 — con qué función del catálogo se corresponde el programa que corrió, si está
    #: registrada. Cierra el circuito de los tres: el catálogo dice qué existe, el evento cuándo
    #: corrió y esto qué hizo al correr.
    funcion_sha256: str | None = None

    categorias_datos: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _explica_lo_que_sobra(cls, datos):
        """Convierte «Extra inputs are not permitted» en algo que se pueda actuar.

        Mismo criterio que el evento de actividad, y por la misma razón: sin esto, la conclusión
        razonable de quien integra es que al esquema le falta un campo, así que pide que se
        añada — y la conversación de explicar que este registro no puede convertirse en un
        segundo sitio donde viven los datos personales acaba teniéndose igual, sólo que a
        posteriori y por un canal lento.
        """
        if not isinstance(datos, dict):
            return datos

        declarados = set(cls.model_fields)

        if "organizacion_id" in datos and "organizacion_id" not in declarados:
            raise ValueError(
                "`organizacion_id` no viaja en el manifiesto: se deriva del token que "
                "autentica la petición. Si se pudiera elegir, un token de una organización "
                "podría depositar evidencia en el registro de otra."
            )

        _explica_el_contenido(datos, declarados, _SUENAN_A_CONTENIDO)
        return datos

    @field_validator("ocurrido_en")
    @classmethod
    def _con_zona_horaria(cls, valor: datetime) -> datetime:
        if valor.tzinfo is None:
            raise ValueError(
                "`ocurrido_en` necesita zona horaria: un instante sin zona no es un instante, y "
                "en un registro que se cruza entre organizaciones eso son horas de diferencia "
                "sin avisar."
            )
        return valor

    @field_validator("hash_de_la_salida", "funcion_sha256")
    @classmethod
    def _es_un_sha256(cls, valor: str | None, info) -> str | None:
        if valor is not None and not _SHA256.match(valor):
            raise ValueError(
                f"`{info.field_name}` tiene que ser un SHA-256 en hexadecimal minúscula (64 "
                "caracteres). Un hash mal formado no sirve para cotejar nada."
            )
        return valor
