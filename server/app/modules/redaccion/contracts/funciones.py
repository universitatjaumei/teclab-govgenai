"""El contrato de una función del catálogo: qué pide, qué devuelve y qué declara (FUN.2).

Deploy: edge.

Hoy el contrato de un script es **implícito** —«tienes `file_path`, `raw_text` y `options`, asigna
`result`»— y eso aguanta mientras quien escribe el script y quien le pasa los datos son la misma
persona el mismo día. En cuanto una función se comparte entre dos plantillas, dos organizaciones y
una API, el contrato implícito es el sitio por donde se rompe todo: un ERP cambia una columna y el
informe falla con un `KeyError` de pandas dentro del sandbox.

Cuatro decisiones, y ninguna es de comodidad:

1. **Un solo objeto para los dos orígenes.** Este `ContratoFuncion` es lo que declara una función
   de autoservicio *y* lo que exporta el descriptor de una empaquetada (FUN.5). Dos esquemas de
   contrato divergen; uno solo es lo que hace que el formulario, la API y —en Fase 3— la fase de
   expediente traten igual a las dos. Ninguna rama «si es paquete».
2. **La salida es `ExtractionResult`, el que ya existe.** No se inventa un segundo esquema: el que
   hay es el que consumen los nodos.
3. **Los parámetros reutilizan `UIFieldDescriptor`** y los slots `UIDropzoneDescriptor`, los mismos
   tipos que `ReportUIContract`. Así el SDUI pinta el formulario desde el contrato, gratis, y no
   hay dos pantallas pintando formularios distintos para lo mismo.
4. **La declaración responsable forma parte del contrato.** Es lo que la Instrucció 02/2026 exige
   registrar antes de compartir (§8.2) y lo que la revisión posterior lee — también en una función
   corporativa: un paquete también declara finalidad y categorías.

Nada aquí sabe de «informe»: el catálogo es pieza compartida.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, Field, model_validator

from server.app.core.actividad_categorias import CATEGORIAS_INICIALES
from server.app.modules.redaccion.contracts.ui import (
    UIDropzoneDescriptor,
    UIFieldDescriptor,
)

#: El vocabulario de categorías de datos **es el del registro de actividad** (REG). Un solo
#: vocabulario en la plataforma, o el catálogo y el registro no se pueden cruzar en una auditoría.
#: Es una semilla y no una definición: el vocabulario es abierto (I4), así que una categoría fuera
#: de la lista se acepta — rechazarla convertiría «esto no está catalogado todavía» en «esta
#: función no se puede declarar», que es lo que empuja al Shadow IT.
CATEGORIAS_CONOCIDAS: tuple[str, ...] = tuple(codigo for codigo, _ in CATEGORIAS_INICIALES)

#: Las clases de fichero que un slot puede pedir. Estructura con consumidor: cada una tiene un
#: pipeline y unas extensiones detrás.
KindDeSlot = Literal["excel", "pdf", "markdown", "text"]

#: Qué extensiones acepta el navegador para cada clase. Vive aquí y no en React: el cliente lo
#: recibe en el descriptor, no lo deduce.
EXTENSIONES_POR_KIND: dict[str, list[str]] = {
    "excel": [".xlsx", ".xlsm", ".csv"],
    "pdf": [".pdf"],
    "markdown": [".md"],
    "text": [".txt"],
}

#: Los tipos de parámetro que el formulario sabe pintar y el validador sabe comprobar.
TIPOS_DE_PARAMETRO: frozenset[str] = frozenset({"text", "number", "boolean", "date", "select"})


class ContratoIncoherente(ValueError):
    """El contrato de una función no se sostiene: no se registra la versión."""


class EntradaNoCumpleElContrato(ValueError):
    """Lo que se le pasa a una función no encaja con lo que declara pedir.

    Es el error que sustituye al *traceback* de pandas cuando un ERP cambia de formato: dice qué
    slot falta o qué parámetro no es de su tipo, **antes** de pagar un subproceso de sandbox.
    """


class SlotDeFichero(BaseModel):
    """Un fichero que la función pide, con su clase y si es obligatorio."""

    slot_id: str = Field(min_length=1, max_length=60)
    kind: KindDeSlot
    required: bool = False
    label: dict[str, str] = Field(default_factory=dict)


class ParametroDeFuncion(UIFieldDescriptor):
    """Un parámetro tipado. **Es un `UIFieldDescriptor`**: el formulario sale de aquí.

    Heredar en vez de declarar un gemelo es lo que garantiza que el contrato y la pantalla no
    puedan divergir: si mañana el descriptor gana un campo, el contrato lo tiene.
    """

    @model_validator(mode="after")
    def _el_tipo_tiene_que_saberse_pintar(self) -> "ParametroDeFuncion":
        if self.field_type not in TIPOS_DE_PARAMETRO:
            raise ValueError(
                f"«{self.field_type}» no es un tipo de parámetro conocido; los que hay son "
                f"{', '.join(sorted(TIPOS_DE_PARAMETRO))}"
            )
        return self


#: Techo de la retención de artefactos, en días. **Lo pone la plataforma, no quien declara.**
#:
#: Sin techo, «la retención se declara» sería «la retención se elige», y el primer contrato que
#: quisiera guardar un año lo guardaría. Treinta días cubre el caso real —producir un fichero,
#: descargarlo y volver a por él si se perdió— sin convertir el almacenamiento en un archivo de
#: documentos ajenos que nadie decidió crear.
#:
#: **No es la política de retención de la plataforma**, que no existe (issue #162). Es el tramo
#: estrecho que AUT.7 necesitaba para no dejar el silencio significando «para siempre».
RETENCION_MAXIMA_DIAS = 30


class ArtefactosDeSalida(BaseModel):
    """Que esta función produce ficheros, cuántos y por cuánto tiempo se guardan (AUT.7).

    **Los topes van en el contrato y no en una constante del servidor.** Una función que saca un
    Excel de 200 KB y otra que saca cincuenta PDF no pueden compartir un número inventado a
    medias entre las dos; y el tope declarado es además lo que la revisión posterior puede leer
    para saber qué se autorizó.
    """

    model_config = {"extra": "forbid"}

    #: Cuántos ficheros como máximo. **Al menos uno**: declarar «produzco hasta cero» sería una
    #: segunda forma de decir «no produzco», y entonces el código tendría que tratar las dos.
    maximo: int = Field(ge=1, le=100)
    maximo_bytes: int = Field(ge=1, le=100_000_000)
    #: Días que se conservan. **Sin defecto a propósito**: es la decisión que la issue dejaba
    #: anotada, y un defecto aquí la tomaría en silencio.
    retencion_dias: int = Field(ge=1, le=RETENCION_MAXIMA_DIAS)


class ContratoFuncion(BaseModel):
    """Lo que una función pide, lo que devuelve y lo que declara.

    `extra="forbid"` a propósito (la lección de REG.1): un campo de más en el contrato de un
    paquete de un tercero es un malentendido, y aceptarlo en silencio lo convierte en una
    diferencia de comportamiento que aparece meses después.
    """

    model_config = {"extra": "forbid"}

    slots: list[SlotDeFichero] = Field(default_factory=list)
    parametros: list[ParametroDeFuncion] = Field(default_factory=list)
    #: La salida es siempre el esquema que ya consumen los nodos. Se declara para que el
    #: contrato sea legible por sí solo, no para poder cambiarla.
    salida: Literal["ExtractionResult"] = "ExtractionResult"
    #: AUT.7 — **nulo significa «esta función no produce ficheros»**, y es el defecto. Las
    #: funciones que ya existen no ganan una capacidad sin pedirla, y una que no lo declara no
    #: puede producirlos: sin eso el tope sería un consejo y cualquier guion escribiría lo que
    #: quisiera en el directorio de salida.
    artefactos: ArtefactosDeSalida | None = None
    #: AUT.8 — los **servidores** de los que esta función puede pedir documentos. Forma parte de
    #: la declaración responsable: enumerar de dónde se lee es decir de dónde vienen los datos.
    #:
    #: **Lista vacía por omisión**, que es «de ninguna parte»: igual que con los artefactos, la
    #: capacidad se pide. Y son servidores y no URL — ver `_origenes_son_servidores`.
    #:
    #: Quien baja es la plataforma, no el guion: la red del sandbox sigue cerrada. Detalle en
    #: `funciones_origenes.py`.
    origenes: list[str] = Field(default_factory=list)

    # ── Declaración responsable (Instrucció §8.2) ──
    finalidad: str = Field(min_length=1)
    categorias_datos: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _los_nombres_no_se_pisan(self) -> "ContratoFuncion":
        """Slots y parámetros comparten espacio de nombres: la entrada es un solo diccionario."""
        vistos: set[str] = set()
        for cual, elementos in (("slot", self.slots), ("parámetro", self.parametros)):
            for elemento in elementos:
                if elemento.slot_id in vistos:
                    raise ValueError(
                        f"«{elemento.slot_id}» está declarado dos veces: un {cual} no puede "
                        "repetir el identificador de otro, porque la entrada es un solo "
                        "diccionario y el segundo pisaría al primero"
                    )
                vistos.add(elemento.slot_id)
        return self

    @model_validator(mode="after")
    def _origenes_son_servidores(self) -> "ContratoFuncion":
        """Cada origen es un **nombre de servidor**: ni URL, ni comodín, ni dirección IP.

        Las tres exclusiones vienen de cómo se salta una lista blanca, no de purismo:

        * **URL**: habría que declarar cada documento —imposible— o aceptar prefijos, y un
          prefijo invita a `https://sede.gva.es@atacante.example/`, que lleva el origen
          declarado dentro y apunta a otro sitio.
        * **Comodín**: `*.gva.es` parece razonable hasta que alguien consigue un subdominio.
        * **Dirección IP**: no dice de quién es el servidor, y salta la comprobación de nombre
          que es la que resuelve y valida cada dirección.
        """
        import ipaddress
        import re

        forma = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
        for origen in self.origenes:
            crudo = (origen or "").strip()
            normalizado = crudo.lower()
            try:
                ipaddress.ip_address(normalizado)
            except ValueError:
                pass
            else:
                raise ValueError(
                    f"«{crudo}» es una dirección IP, y un origen se declara por nombre de "
                    "servidor: una IP no dice de quién es y salta la comprobación del nombre"
                )
            if not forma.match(normalizado):
                raise ValueError(
                    f"«{crudo}» no es un nombre de servidor. Se declara el servidor —"
                    "`sede.gva.es`— y no una URL ni un comodín: un prefijo de URL se burla con "
                    "`https://sede.gva.es@atacante.example/`, y un comodín lo hereda cualquiera "
                    "que consiga un subdominio"
                )
        return self

    @model_validator(mode="after")
    def _la_declaracion_dice_algo(self) -> "ContratoFuncion":
        if not [c for c in self.categorias_datos if c and c.strip()]:
            raise ValueError(
                "hay que declarar las categorías de datos: una lista vacía es ambigua entre "
                "«no hubo datos personales» y «no lo declaré», y el vocabulario tiene un código "
                "para lo primero (`sin_datos_personales`)"
            )
        return self


class EntradaValidada(BaseModel):
    """Lo que se le pasa a una función una vez comprobado contra su contrato.

    **`ficheros` son referencias, no rutas, y no se abren.** Guardan lo que pidió quien llama
    —una clave del almacenamiento de la organización— y sirven para la **procedencia**: un
    informe cita de dónde salió cada cifra, y meses después esa cita tiene que seguir
    significando algo, cosa que una ruta temporal no hace.

    Para **leer** el fichero está `fichero(slot)`, y la diferencia no es de estilo (APER.14).
    Antes `ficheros` contenía una cadena que el paquete abría con `open()`, y eso tenía dos
    consecuencias: con `STORAGE_BACKEND=gcs` una clave de GCS no es una ruta local y la función
    no funcionaba, y con el backend de ficheros **quien llamaba elegía qué fichero del servidor
    se abría**. Ahora resuelve la plataforma, contra el almacenamiento y con la clave validada.
    """

    model_config = {"arbitrary_types_allowed": True}

    ficheros: dict[str, str] = Field(default_factory=dict)
    parametros: dict[str, Any] = Field(default_factory=dict)
    #: El almacenamiento con el que se resuelven las referencias. Lo pone la plataforma al
    #: construir la entrada; un test de un paquete puede inyectar un doble.
    almacen: Any = Field(default=None, exclude=True, repr=False)

    @asynccontextmanager
    async def fichero(self, slot_id: str) -> AsyncIterator[Path]:
        """La referencia del slot, materializada en una ruta local que existe mientras dure el
        bloque.

            async with entrada.fichero("gastos") as ruta:
                libro = openpyxl.load_workbook(ruta)

        Se entrega una **ruta** y no un objeto de fichero porque es lo que quieren las
        bibliotecas de análisis (`openpyxl`, `pandas.read_excel`, `pdfplumber`), y pelearse con
        eso sería empujar a cada paquete a escribir su propio temporal.

        **Se borra al salir**, y no es cortesía: el contenedor es efímero y un temporal que
        sobrevive es una copia del documento de un cliente esperando a que alguien la encuentre.
        """
        try:
            referencia = self.ficheros[slot_id]
        except KeyError as fallo:
            raise KeyError(
                f"el slot «{slot_id}» no está en esta entrada: la plataforma valida el contrato "
                "antes de llamar, así que pedirlo aquí es pedir algo que la función no declaró"
            ) from fallo

        if self.almacen is None:
            raise RuntimeError(
                f"no hay almacenamiento con el que resolver «{slot_id}». La plataforma lo "
                "inyecta al ejecutar; si estás probando el paquete, pásale un doble en "
                "`EntradaValidada(almacen=…)`."
            )

        contenido = await self.almacen.get(referencia)

        # El sufijo se conserva porque muchas bibliotecas deciden el formato por la extensión.
        sufijo = PurePosixPath(referencia).suffix

        # **Crear el temporal, escribirlo y borrarlo van a un hilo (APER.25).** Esto corre en la
        # ruta de una petición, y las tres son operaciones de disco síncronas: mientras
        # trabajan, el bucle no atiende a nadie más. El tamaño no lo decidimos nosotros, lo
        # decide el documento que suba el cliente, así que la regla de asincronía total de
        # `AGENTS.md` aplica aquí aunque en un fichero de prueba de dos kilobytes no se note.
        def _materializar() -> Path:
            ruta = Path(tempfile.mkdtemp(prefix="govgenai-funcion-")) / f"entrada{sufijo}"
            ruta.write_bytes(contenido)
            return ruta

        destino = await asyncio.to_thread(_materializar)
        try:
            yield destino
        finally:
            # En el `finally`, o sea que corre siempre: borrar un árbol también es trabajo de
            # disco, y no se hace en el bucle.
            await asyncio.to_thread(shutil.rmtree, destino.parent, ignore_errors=True)


class FormularioDeFuncion(BaseModel):
    """Los descriptores con los que el SDUI pinta la entrada de una función."""

    dropzones: list[UIDropzoneDescriptor] = Field(default_factory=list)
    campos: list[UIFieldDescriptor] = Field(default_factory=list)


def contrato_coherente(contrato: ContratoFuncion, *, exige_entrada: bool = False) -> None:
    """Comprueba lo que Pydantic no puede: que el contrato tenga sentido como contrato.

    `exige_entrada` lo usa el registro de una versión que declara leer ficheros; una función que
    sólo toma parámetros es legítima, así que no se exige siempre.
    """
    if exige_entrada and not contrato.slots and not contrato.parametros:
        raise ContratoIncoherente(
            "el contrato no declara ningún slot ni ningún parámetro: una función que no pide "
            "nada no puede recibir los datos del informe"
        )


def descriptores_de_formulario(contrato: ContratoFuncion) -> FormularioDeFuncion:
    """El formulario que el SDUI pinta, derivado del contrato.

    Aquí es donde se paga el precio de haber declarado el contrato, y donde se cobra: el
    frontend no conoce ni un campo a priori (regla maestra 1).
    """
    return FormularioDeFuncion(
        dropzones=[
            UIDropzoneDescriptor(
                slot_id=slot.slot_id,
                label=slot.label or {"es": slot.slot_id},
                accept=list(EXTENSIONES_POR_KIND.get(slot.kind, [])),
                multiple=False,
                required=slot.required,
            )
            for slot in contrato.slots
        ],
        campos=[
            UIFieldDescriptor(
                slot_id=p.slot_id,
                label=p.label,
                field_type=p.field_type,
                placeholder=p.placeholder,
                required=p.required,
            )
            for p in contrato.parametros
        ],
    )


def validar_entrada(
    contrato: ContratoFuncion,
    *,
    ficheros: dict[str, str] | None = None,
    parametros: dict[str, Any] | None = None,
    almacen: Any = None,
    slots_ya_traidos: set[str] | None = None,
) -> EntradaValidada:
    """La entrada comprobada contra el contrato, **antes** de invocar nada.

    Levanta `EntradaNoCumpleElContrato` con el nombre de lo que falla. Validar después sería
    pagar un subproceso para obtener un error peor.

    `slots_ya_traidos` (AUT.8) son los slots que la plataforma **ya bajó** de un origen
    declarado: cuentan como presentes aunque no tengan referencia de almacenamiento. Va como
    parámetro explícito y no metiendo un marcador falso en `ficheros`, que es la otra forma de
    conseguirlo: ese marcador viaja luego al guion dentro de `options["ficheros"]` y sería una
    ruta que no existe con aspecto de ruta.
    """
    ficheros = dict(ficheros or {})
    parametros = dict(parametros or {})
    traidos = set(slots_ya_traidos or ())

    declarados = {slot.slot_id: slot for slot in contrato.slots}
    for slot_id, slot in declarados.items():
        if slot.required and not ficheros.get(slot_id) and slot_id not in traidos:
            raise EntradaNoCumpleElContrato(
                f"falta el slot «{slot_id}», que el contrato declara obligatorio"
            )
    for slot_id in set(ficheros) | traidos:
        if slot_id not in declarados:
            raise EntradaNoCumpleElContrato(
                f"el slot «{slot_id}» no está en el contrato de esta función: o alguien lo "
                "cambió sin avisar, o se están mandando datos que la función no pidió"
            )

    for parametro in contrato.parametros:
        presente = parametro.slot_id in parametros
        if parametro.required and not presente:
            raise EntradaNoCumpleElContrato(
                f"falta el parámetro «{parametro.slot_id}», que el contrato declara obligatorio"
            )
        if presente:
            _comprobar_tipo(parametro, parametros[parametro.slot_id])

    return EntradaValidada(ficheros=ficheros, parametros=parametros, almacen=almacen)


def _comprobar_tipo(parametro: ParametroDeFuncion, valor: Any) -> None:
    """El tipo de un parámetro, comprobado con el mensaje que necesita quien rellena el formulario."""
    tipo = parametro.field_type
    if tipo == "number":
        # `bool` es subclase de `int` en Python y aquí eso sería un sí por un 1.
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise EntradaNoCumpleElContrato(
                f"el parámetro «{parametro.slot_id}» tiene que ser numérico y ha llegado "
                f"«{valor}»"
            )
    elif tipo == "boolean":
        if not isinstance(valor, bool):
            raise EntradaNoCumpleElContrato(
                f"el parámetro «{parametro.slot_id}» tiene que ser un sí o un no"
            )
    elif tipo in {"text", "date", "select"}:
        if not isinstance(valor, str):
            raise EntradaNoCumpleElContrato(
                f"el parámetro «{parametro.slot_id}» tiene que ser texto"
            )
