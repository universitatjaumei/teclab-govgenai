"""Wrappers que envuelven el código de usuario antes de pasarlo al subproceso.

Todos los wrappers:
- Usan `repr()` para serializar valores Python (literales True/False/None).
- Inyectan el código de usuario como texto Python literal entre marcadores.
- Imprimen el resultado al stdout (extraction) o lo escriben a fichero (chart/etl).
"""
from __future__ import annotations

from typing import Any


def build_extraction_wrapper(
    code: str,
    file_path: str,
    raw_text: str,
    options: dict[str, Any],
    output_dir: str = "",
) -> str:
    """Envuelve el código de extracción y serializa `result` como JSON al stdout.

    `output_dir` (AUT.7) es el único sitio donde el guion puede dejar ficheros. Va como variable
    y no como función de ayuda porque el protocolo del script ya es así —`file_path`, `raw_text`,
    `options`— y cambiarlo obligaría a reescribir los guiones que funcionan.

    **No hay forma de escribir a mano**: el auditor deniega `open`, así que un guion produce
    ficheros a través de una librería (`df.to_excel(...)`, `doc.save(...)`). Eso no es una
    incomodidad, es lo que mantiene acotado qué puede aparecer ahí.
    """
    return f"""\
import sys, json, math, re, datetime, collections, typing, io

try:
    import pandas
except ImportError:
    pandas = None

file_path = {file_path!r}
raw_text = {raw_text!r}
options = {options!r}
output_dir = {output_dir!r}

# --- script de usuario ---
{code}
# --- fin script de usuario ---

_r = globals().get("result", {{}})
print(json.dumps(_r, default=str))
"""


def build_chart_wrapper(
    code: str,
    csv_path: str,
    output_path: str,
    output_format: str,
) -> str:
    """Carga el CSV en `df`, ejecuta el código del usuario y guarda la imagen."""
    return f"""\
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import io, math, re

df = pd.read_csv({csv_path!r})

# --- user code ---
{code}
# --- end user code ---

plt.savefig({output_path!r}, format={output_format!r}, dpi=150, bbox_inches="tight", facecolor="white")
plt.close("all")
"""


def build_etl_wrapper(
    code: str,
    in_csv_path: str,
    out_csv_path: str,
) -> str:
    """Carga el CSV en `df`, espera que el usuario defina `transform(df)`.

    Si no define `transform`, escribe el sentinel `ETL_TRANSFORM_UNDEFINED` en
    stderr y sale con código 7, que el endpoint /execute-etl traduce en 422
    `ETL_NO_TRANSFORM`.
    """
    return f"""\
import sys
import pandas as pd

df = pd.read_csv({in_csv_path!r})

# --- user code ---
{code}
# --- end user code ---

_transform = globals().get("transform")
if not callable(_transform):
    print("ETL_TRANSFORM_UNDEFINED", file=sys.stderr)
    sys.exit(7)

_out = _transform(df.copy())
_out.to_csv({out_csv_path!r}, index=False)
"""
