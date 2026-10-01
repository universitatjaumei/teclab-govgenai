"""Anonimizar un fichero tabular para compartirlo o publicarlo (UTL.2, issue #191).

Deploy: edge.

El flujo es el del legacy (`client_app/app/services/anonymization_service.py` y su pantalla):
subir → analizar y **proponer** tipo y regla por columna → que la persona ajuste → previsualizar
→ descargar. El motor es el de la plataforma (`AnonymizationContext`), que ya tenía portados los
modos del legacy; esto es lo que faltaba para usarlo con un fichero.

**Sólo CSV y Excel** (decisión del usuario, 2026-10-01). Un Word o un PDF anonimizado es reescribir
el documento manteniendo su formato, y es otro problema. Del Excel se lee **la primera hoja**, y
el análisis lo dice cuando hay más.

**No se promete que el resultado sea anónimo.** Es seudonimización asistida: el detector no ve
todo, y quien publica sigue siendo responsable. La pantalla lo dice, y exige confirmar que se ha
revisado la vista previa antes de descargar.

**Por qué el detector es éste.** Se midió el 2026-10-01 contra el detector de texto de la
plataforma aplicado celda a celda, sobre un listado sintético de 10 columnas con su tipo conocido:
por columnas acertó 10 de 10, con cabeceras normales y con cabeceras neutras (`col1`, `col2`…);
celda a celda, 8 de 10, porque marcaba los importes como organizaciones y las fechas como dato
personal. Es una muestra pequeña y sintética: dice qué detector equivoca menos la forma de un
listado, no cuánto acierta con uno real.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

import pandas as pd

from server.app.modules.redaccion.services.anonymization.anonymizer import (
    AnonymizationContext,
    letra_de_documento_valida,
)
from server.app.modules.redaccion.services.anonymization.pii_detector import PiiDetector

#: Las reglas que admite cada tipo, con la que se propone primero.
#:
#: `TEXTO` es el texto libre: «Hablar con Ana García» se detecta bien como nombres, pero sustituir
#: la celda por un nombre falso borraría el texto que lo rodea. Su regla cambia sólo lo que
#: encuentra dentro.
MODOS_POR_TIPO: dict[str, tuple[str, ...]] = {
    "DNI": ("AEPD", "MASK", "FAKER"),
    "NIE": ("AEPD", "MASK", "FAKER"),
    "PASSPORT": ("AEPD", "MASK", "FAKER"),
    "PERSON_NAME": ("FAKER", "INITIALS", "MASK"),
    "TEXTO": ("TEXTO",),
    "EMAIL": ("MASK", "FAKER"),
    "PHONE": ("MASK", "FAKER"),
    "IBAN": ("MASK", "FAKER"),
    "CREDIT_CARD": ("MASK", "FAKER"),
    "NSS": ("MASK", "FAKER"),
    "ADDRESS": ("FAKER", "MASK"),
    "ORGANIZATION": ("FAKER", "MASK"),
}

#: Los tipos que se pueden elegir. `NONE` es «no es dato personal»: la columna se deja.
TIPOS = ("NONE", *MODOS_POR_TIPO)

#: `NINGUNO` vale para cualquier tipo: es dejar la columna como está, decidiéndolo.
NINGUNO = "NINGUNO"

#: Cuántas filas enseña la vista previa.
FILAS_DE_VISTA_PREVIA = 20

#: Qué categoría de datos del registro corresponde a cada tipo, para anotar el uso.
CATEGORIA_POR_TIPO: dict[str, str] = {
    "DNI": "datos_identificativos",
    "NIE": "datos_identificativos",
    "PASSPORT": "datos_identificativos",
    "PERSON_NAME": "datos_identificativos",
    "TEXTO": "datos_identificativos",
    "NSS": "datos_identificativos",
    "EMAIL": "datos_de_contacto",
    "PHONE": "datos_de_contacto",
    "ADDRESS": "datos_de_contacto",
    "IBAN": "datos_economicos_y_financieros",
    "CREDIT_CARD": "datos_economicos_y_financieros",
}


class FicheroNoValido(ValueError):
    """El fichero no es un CSV ni un Excel que se pueda leer. El mensaje dice por qué."""


class ReglaNoValida(ValueError):
    """Una regla que no se puede aplicar. El mensaje dice cuál y por qué."""


@dataclass
class Tabla:
    df: pd.DataFrame
    formato: str  # "csv" | "xlsx"
    separador: str = ","
    hojas: int = 1


@dataclass(frozen=True)
class Regla:
    tipo: str
    modo: str


@dataclass
class Propuesta:
    columna: str
    tipo: str
    modo: str
    modos_posibles: tuple[str, ...]
    confianza: float
    ejemplos: list[str] = field(default_factory=list)


def _formato(nombre: str) -> str:
    extension = (nombre or "").rsplit(".", 1)[-1].lower() if "." in (nombre or "") else ""
    if extension == "csv":
        return "csv"
    if extension in ("xlsx", "xlsm"):
        return "xlsx"
    raise FicheroNoValido(
        "sólo se pueden anonimizar ficheros CSV o Excel (.xlsx). Un Word o un PDF es otro "
        "problema —hay que reescribir el documento manteniendo el formato— y no está aquí."
    )


def leer_tabla(datos: bytes, nombre: str) -> Tabla:
    """El fichero como tabla. En el CSV se deduce el separador; del Excel, la primera hoja."""
    formato = _formato(nombre)
    if formato == "csv":
        try:
            texto = datos.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = datos.decode("cp1252")
        try:
            separador = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            separador = ","
        try:
            df = pd.read_csv(
                io.StringIO(texto), sep=separador, dtype=str, keep_default_na=False
            )
        except Exception as fallo:  # noqa: BLE001 — pandas lanza varios tipos; el motivo va dentro
            raise FicheroNoValido(f"el CSV no se puede leer: {fallo}") from fallo
        return Tabla(df=df, formato="csv", separador=separador)

    try:
        libro = pd.ExcelFile(io.BytesIO(datos), engine="openpyxl")
        df = libro.parse(libro.sheet_names[0], dtype=object)
    except Exception as fallo:  # noqa: BLE001
        raise FicheroNoValido(f"el Excel no se puede leer: {fallo}") from fallo
    return Tabla(df=df, formato="xlsx", hojas=len(libro.sheet_names))


def _es_texto_libre(valores: list[str], detector: PiiDetector) -> bool:
    """Si la columna es texto con nombres dentro, y no nombres.

    Una celda es texto cuando tiene cuatro palabras o más y lo detectado no la cubre casi entera.
    Si la mayoría de las celdas con algo detectado lo son, la columna se propone como `TEXTO`.
    """
    con_nombre = 0
    de_texto = 0
    for valor in valores:
        tramos = [s for s in detector.detect_spans(valor) if s.type == "PERSON_NAME"]
        if not tramos:
            continue
        con_nombre += 1
        cubierto = sum(s.end - s.start for s in tramos)
        if len(valor.split()) >= 4 and cubierto < 0.8 * len(valor.strip()):
            de_texto += 1
    return con_nombre > 0 and de_texto * 2 >= con_nombre


def analizar(tabla: Tabla) -> list[Propuesta]:
    """Una propuesta por columna: qué parece, qué regla se propone y unos ejemplos."""
    contexto = AnonymizationContext(faker_seed=0)
    detector = PiiDetector(contexto)
    analisis = {str(a["field"]): a for a in contexto.analyze_fields(tabla.df)}

    propuestas = []
    for columna in tabla.df.columns:
        nombre = str(columna)
        serie = tabla.df[columna]
        valores = [str(v) for v in serie.dropna().tolist() if str(v).strip()][:10]
        entrada = analisis.get(nombre, {})
        tipo = entrada.get("pii_type", "NONE")
        confianza = float(entrada.get("confidence", 0.0))

        # El nombre de la cabecera manda sobre el contenido para decir «esto son nombres»; si
        # la cabecera no lo dice, el contenido decide si es texto libre.
        if tipo == "PERSON_NAME" and contexto._analyze_header(nombre) != "PERSON_NAME":
            if _es_texto_libre(valores, detector):
                tipo = "TEXTO"
        if tipo in ("DNI", "NIE") and valores:
            # La letra del documento da confianza; no quita la propuesta si falla.
            validos = sum(letra_de_documento_valida(v) for v in valores) / len(valores)
            confianza = max(confianza, validos)

        modos = MODOS_POR_TIPO.get(tipo, ())
        propuestas.append(
            Propuesta(
                columna=nombre,
                tipo=tipo,
                modo=modos[0] if modos else NINGUNO,
                modos_posibles=(*modos, NINGUNO),
                confianza=round(min(confianza, 1.0), 2),
                ejemplos=valores[:3],
            )
        )
    return propuestas


def _comprobar(df: pd.DataFrame, reglas: dict[str, Regla]) -> None:
    for columna, regla in reglas.items():
        if columna not in df.columns:
            raise ReglaNoValida(f"el fichero no tiene ninguna columna «{columna}»")
        if regla.modo == NINGUNO:
            continue
        if regla.tipo not in MODOS_POR_TIPO:
            raise ReglaNoValida(
                f"«{regla.tipo}» no es un tipo que se pueda anonimizar en «{columna}»"
            )
        if regla.modo not in MODOS_POR_TIPO[regla.tipo]:
            raise ReglaNoValida(
                f"la regla «{regla.modo}» no vale para {regla.tipo} en «{columna}»; las que "
                f"valen son {', '.join(MODOS_POR_TIPO[regla.tipo])}"
            )


def aplicar(df: pd.DataFrame, reglas: dict[str, Regla], *, semilla: int) -> pd.DataFrame:
    """Aplica las reglas al fichero entero. La misma semilla da el mismo resultado.

    La semilla es lo que hace que la vista previa sea la descarga: las dos llaman aquí con la
    misma, sobre el fichero entero, y un FAKER distinto entre una y otra haría que la persona
    revisara algo que no es lo que va a compartir.
    """
    _comprobar(df, reglas)
    contexto = AnonymizationContext(faker_seed=semilla)
    config = {}
    for columna, regla in reglas.items():
        if regla.modo == NINGUNO:
            continue
        if regla.tipo == "TEXTO":
            # Un tipo que el motor no conoce va por `anonymize`, que cambia sólo lo detectado.
            config[columna] = {"type": "TEXTO_LIBRE", "mode": "FAKER"}
        else:
            config[columna] = {"type": regla.tipo, "mode": regla.modo}
    return contexto.anonymize_dataframe(df, config)


def escribir(df: pd.DataFrame, tabla: Tabla) -> bytes:
    """El fichero en el mismo formato en que llegó."""
    if tabla.formato == "csv":
        return df.to_csv(index=False, sep=tabla.separador).encode("utf-8-sig")
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def filas(df: pd.DataFrame, n: int = FILAS_DE_VISTA_PREVIA) -> list[list[str]]:
    """Las primeras filas como texto, para enseñarlas. Una celda vacía sale como cadena vacía."""
    return [["" if pd.isna(v) else str(v) for v in fila] for fila in df.head(n).itertuples(index=False)]
