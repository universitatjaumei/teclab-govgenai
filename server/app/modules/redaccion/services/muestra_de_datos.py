"""Resumen de la estructura de un fichero, para que la IA proponga sobre datos que ha visto.

Deploy: edge

`propose` recibía solo el texto de la petición, así que pedirle a un modelo la estructura de un
informe sobre un CSV cuyas columnas no ha visto era pedirle que adivinara. En las pruebas del
2026-08-20 adivinó mal.

El legacy sí mandaba el contexto del fichero
(`client_app/app/modules/factory/etl_factory.py:146-200`):

    'columns': list(df.columns),
    'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()},
    'sample_rows': df.head(3).to_dict(orient='records'),
    'row_count': len(df)

y **anonimizaba la muestra antes de enviarla** (línea 152). Esto recupera ese diseño.

**La anonimización pasa aquí**, en el servicio edge, no en `model_factory`: por la frontera
edge-cloud de `CLAUDE.md`, el factory recibe datos ya anonimizados y no anonimiza. Los nombres
de columna se conservan tal cual —son estructura, no dato personal, y son justo lo que el modelo
necesita para no inventarse campos—; lo que se anonimiza son los **valores** de las tres filas.
"""
from __future__ import annotations

import io

from pydantic import BaseModel, Field

#: Cuántas filas se enseñan. Tres, como el legacy: bastantes para ver la forma de los datos
#: —si el importe viene como texto, si el periodo es `202608`—, pocas para no volcar el fichero
#: en un prompt.
FILAS_DE_MUESTRA = 3


class MuestraIlegibleError(ValueError):
    """El fichero no se pudo leer como tabla.

    Es un fallo **del fichero**, no del servidor: sale como error de dominio para que el router
    lo traduzca a 422 y quien lo subió sepa que tiene que aportar otro, en vez de ver un 500.
    """


class MuestraDeDatos(BaseModel):
    """La estructura de un fichero, sin sus datos personales."""

    nombre_del_fichero: str
    columnas: list[str]
    #: Tipo inferido por columna, en texto. Que `saldo` salga como `str` (`object` antes de pandas 3) es información:
    #: significa que los importes vienen como texto y que hay que convertirlos antes de sumar.
    tipos: dict[str, str] = Field(default_factory=dict)
    filas_totales: int = 0
    primeras_filas: list[dict] = Field(default_factory=list)


def resumen_de_la_muestra(contenido: bytes, nombre_del_fichero: str) -> MuestraDeDatos:
    """Lee el fichero, resume su estructura y anonimiza los valores de la muestra."""
    marco = _leer_como_tabla(contenido, nombre_del_fichero)

    filas = marco.head(FILAS_DE_MUESTRA).to_dict(orient="records")

    return MuestraDeDatos(
        nombre_del_fichero=nombre_del_fichero,
        columnas=[str(c) for c in marco.columns],
        tipos={str(c): str(t) for c, t in marco.dtypes.items()},
        filas_totales=int(len(marco)),
        primeras_filas=_anonimizadas(filas),
    )


def _leer_como_tabla(contenido: bytes, nombre: str):
    """El fichero como DataFrame, sin convertir nada.

    `dtype=str` a propósito en el CSV: convertir «1.234,56» a número aquí escondería el
    problema que el modelo tiene que ver. Lo que importa es la forma real del dato.
    """
    import pandas as pd

    minusculas = nombre.lower()
    try:
        if minusculas.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(contenido))
        if minusculas.endswith((".csv", ".txt")):
            return pd.read_csv(io.BytesIO(contenido), dtype=str)
        raise MuestraIlegibleError(
            f"No se sabe leer {nombre!r} como tabla: se admiten .csv, .xlsx y .xls"
        )
    except MuestraIlegibleError:
        raise
    except Exception as fallo:  # noqa: BLE001
        raise MuestraIlegibleError(f"No se pudo leer {nombre!r} como tabla: {fallo}") from fallo


def _anonimizadas(filas: list[dict]) -> list[dict]:
    """Las filas con sus datos personales sustituidos.

    Si el anonimizador no está disponible —le falta el modelo de spaCy, por ejemplo— la muestra
    **no sale**: es preferible proponer sin ver los datos que mandar datos sin anonimizar a un
    modelo que puede estar en la nube.
    """
    from server.app.modules.redaccion.services.anonymization.anonymizer import (
        AnonymizationContext,
    )

    contexto = AnonymizationContext()
    return [contexto.anonymize(fila) for fila in filas]
