# Anonimizar el presupuesto propio (AUT.10, issue #120).
#
# Primera de las dos funciones en que se convierte el cuaderno «Pressupost UJI»: quita los nombres
# de personas de las descripciones del presupuesto antes de que nada más lo toque. La segunda
# (`documento_presupuesto.py`) recibe lo que ésta produce.
#
# Es la anonimización **del cuaderno**, no la de la plataforma, y a propósito: es determinista y
# del dominio —busca códigos de convocatoria (`PID2023-…`, `CIDEGENT/2024/…`) seguidos de un nombre,
# y nombres del personal investigador que estén en la lista del PDI—, y el servicio general de la
# plataforma no conoce ninguna de las dos cosas. Sustituirlo cambiaría qué se tacha.
#
# Diferencias con el cuaderno. Las dos primeras protegen más; las tres últimas son defectos suyos
# que destaparon los tests con datos sintéticos:
#
# * **Sustituye en su sitio.** El cuaderno añadía columnas `*_anon` y **conservaba las originales**,
#   así que su CSV «limpio» llevaba los nombres al lado. Aquí la columna original sale ya tachada.
# * **Vacía el NIF del tercero en los gastos**, que es donde el tercero puede ser una persona. En los
#   ingresos el tercero es la entidad que financia y se conserva, como en el cuaderno.
# * **La lista STOP funcionaba al revés**: se comparaba en minúsculas contra una lista en mayúsculas
#   y no coincidía nunca, así que se tachaban títulos de proyecto como si fueran nombres.
# * **De dos personas en una descripción, la segunda quedaba a la vista**: se sustituía una vez.
# * **El gazetteer se comía la partícula** que une con la persona siguiente («… Soler i»).
#
# Protocolo de la plataforma: los ficheros llegan en `options["ficheros"]` por su slot, lo que el
# guion escribe en `output_dir` es un artefacto, y `result` lleva las cifras.
import re
import unicodedata

import pandas as pd

MARCADOR = "[IP - dada protegida]"

# Códigos de convocatoria: un nombre detrás de uno de éstos es el de quien la tiene.
CODIS = [
    r"JDC\d{4}-\d+(?:-[A-Z0-9](?![A-Za-zÀ-ÿ0-9]))?", r"FJC\d{4}-\d+(?:-[A-Z0-9](?![A-Za-zÀ-ÿ0-9]))?",
    r"IJC\d{4}-\d+(?:-[A-Z0-9](?![A-Za-zÀ-ÿ0-9]))?", r"RYC\d{4}-\d+(?:-[A-Z0-9](?![A-Za-zÀ-ÿ0-9]))?",
    r"PRE\d{4}-\d+", r"PID\d{4}-\S+", r"PDC\d{4}-\S+", r"TED\d{4}-\S+", r"CNS\d{4}-\d+",
    r"CIAPOS/\d{4}/\d+", r"CIACIF/\d{4}/\d+", r"APOSTD/\d{4}/\d+", r"ACIF/\d{4}/\d+",
    r"CIDEGENT/\d{4}/\d+", r"CIDEXG/\d{4}/\d+", r"CIGE/\d{4}/\d+", r"INNEST/\d{4}/\d+",
    r"CIPROM/\d{4}/\d+", r"CISEJI/\d{4}/\d+", r"CIAEST/\d{4}/\d+", r"CIGRIS/\d{4}/\d+",
    r"CIAICO/\d{4}/\d+", r"CIDEIG/\d{4}/\d+", r"CIESGT/\d{4}/\d+", r"CCPGI/\d{4}/\d+",
    r"GRISOLIAP?/\d{4}/\d+", r"GACUJIMB/\d{4}/\d+", r"INN[A-Z]{2}[0-9]?/\d{4}/\d+",
    r"PREP\d{4}-\d+", r"PTA\d{4}-\d+(?:-[A-Z](?![A-Za-zÀ-ÿ]))?", r"CPP\d{4}-\d+",
    r"PLEC\d{4}-\d+", r"BG\d{2}/\d+", r"UJI-\d{4}-\d+", r"GVA-[A-Z0-9/]+",
]
# Nombres de programa que van entre el código y el nombre y no son el nombre.
PROGRAMES = [
    r"JUAN DE LA CIERVA(?:\s+FORMACI[ÓO])?(?:\s+INCORPORACI[ÓO]N?)?(?:\s+\d{4})?",
    r"RAM[OÓ]N?\s+Y\s+CAJAL(?:\s+\d{4})?", r"SANTIAGO\s+GRISOL[IÍ]A(?:\s+\d{4})?",
    r"MAR[IÍ]A\s+ZAMBRANO(?:\s+\d{4})?", r"BEATRIZ\s+GALINDO(?:\s+\d{4})?",
    r"AJUDES?\s+A\s+LA\s+CONSOLIDACI[ÓO]\s+INVESTIGADORA",
    r"AYUDAS?\s+A\s+LA\s+CONSOLIDACI[ÓO]N\s+INVESTIGADORA",
    r"\(\s*GRISOL[IÍ]A(?:\s+\d{4})?\s*\)", r"\(\s*CIDEGENT(?:\s+\d{4})?\s*\)",
    r"CIDEGENT(?:\s+\d{4})?", r"FORMACI[ÓO](?:\s+\d{4})?", r"INCORPORACI[ÓO]N?(?:\s+\d{4})?",
]
PARTICULES = {"de", "del", "dels", "de la", "de las", "de los", "la", "las", "los",
              "i", "y", "e", "van", "von", "der", "da", "das", "do", "dos", "al", "el",
              "bin", "ben", "sant", "santa"}
# Palabras que, si aparecen, dicen que el texto es un proyecto y no un nombre.
STOP = {"SISTEMA", "SISTEMES", "PARA", "PER", "TRAVES", "TRAVÉS", "GESTIO", "GESTIÓ", "GESTION",
        "GESTIÓN", "RED", "XARXA", "PROYECTO", "PROJECTE", "PROGRAMA", "DIGITALIZACION",
        "DIGITALIZACIÓN", "DIGITALITZACIO", "ENERGETICA", "ENERGÉTICA", "INTELIGENTE",
        "INTEL·LIGENT", "OPTIMIZACION", "OPTIMIZACIÓN", "REUTILIZACION", "AGUA", "AIGUA", "RIEGO",
        "REG", "CATEDRA", "CÀTEDRA", "CONVENI", "CONVENIO", "CONTRACTE", "CONTRATO", "UNIVERSITAT",
        "UNIVERSIDAD", "AJUNTAMENT", "DIPUTACIO", "DIPUTACIÓ", "GENERALITAT", "FUNDACION",
        "FUNDACIÓ", "FUNDACIÓN", "MINISTERIO", "CONSELLERIA", "TECHNOLOGY", "INDUSTRY", "TOWARDS",
        "THROUGH", "DECARBONIZATION", "INNOVATIVE", "GRANULATED"}

_RE_CODIS = [re.compile(p, re.I | re.U) for p in CODIS]
_RE_PROG = [re.compile(p, re.I | re.U) for p in PROGRAMES]
TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’·.\-]*", re.U)

# Las columnas del CSV de partida que llevan texto libre. Se anonimizan **en su sitio**.
COLUMNAS_DE_TEXTO = [
    "Descr Proj", "Nombre Subproyecto", "Expediente Pluri Nombre",
    "Observacion", "Comentario Centro",
]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


# STOP **normalizada**, que es como se compara. El cuaderno comparaba `norm(t)` —minúsculas, sin
# acentos— contra la lista en mayúsculas, así que no coincidía nunca: cualquier título de proyecto
# de dos a seis palabras detrás de un código se tachaba como si fuera un nombre. Lo destapó el test
# de «lo que no es una persona sigue como estaba».
STOP_NORM = {norm(p) for p in STOP}


def _find_codi(desc):
    for rx in _RE_CODIS:
        m = rx.search(desc)
        if m:
            return m
    return None


def _strip_prog(text):
    for rx in _RE_PROG:
        text = rx.sub(" ", text)
    return text


def _looks_like_name(residu):
    r = residu.strip(" -,;.·")
    if not r:
        return None
    toks = TOKEN_RE.findall(r)
    if len(toks) < 2 or len(toks) > 6:
        return None
    for t in toks:
        if norm(t) in STOP_NORM or any(ch.isdigit() for ch in t):
            return None
    forts = [t for t in toks if norm(t) not in PARTICULES]
    return r if len(forts) >= 2 else None


def _anon_codi(desc):
    m = _find_codi(desc)
    if not m:
        return desc, None
    residu = _strip_prog(desc[m.end():]).strip(" -,;.·")
    nom = _looks_like_name(residu)
    if not nom:
        return desc, None
    if nom in desc:
        return desc.replace(nom, MARCADOR, 1), nom
    return desc.replace(residu, MARCADOR, 1), nom


def build_pdi_index(lineas):
    idx = {}
    for line in lineas:
        line = str(line).strip()
        if not line:
            continue
        toks = TOKEN_RE.findall(line)
        strong = [norm(t) for t in toks if norm(t) not in PARTICULES and len(norm(t)) >= 2]
        if len(strong) >= 2:
            idx.setdefault(frozenset(strong), line)
    return idx


def _anon_gazetteer(desc, idx):
    if not idx:
        return desc, None
    spans = [(m.start(), m.end(), m.group(0)) for m in TOKEN_RE.finditer(desc)]
    n = len(spans)
    for L in (6, 5, 4, 3, 2):
        for i in range(0, n - L + 1):
            w = spans[i:i + L]
            # Una ventana no empieza ni acaba en partícula: «Marta Ferrer Soler i» casaba antes que
            # «Marta Ferrer Soler» —se prueban primero las largas y las partículas no cuentan— y la
            # sustitución se comía la «i» que une con la persona siguiente.
            if norm(w[0][2]) in PARTICULES or norm(w[-1][2]) in PARTICULES:
                continue
            strong = [norm(x[2]) for x in w if norm(x[2]) not in PARTICULES and len(norm(x[2])) >= 2]
            if len(strong) < 2 or any(norm(x[2]) in STOP_NORM for x in w):
                continue
            if frozenset(strong) in idx:
                s, e = w[0][0], w[-1][1]
                return desc[:s] + MARCADOR + desc[e:], desc[s:e]
    return desc, None


def anonimitza_text(desc, idx):
    """Primero por código + residuo, **una vez**; después el gazetteer del PDI, hasta que no quede.

    El cuaderno hacía una sola sustitución en total, así que de dos personas en la misma
    descripción la segunda quedaba a la vista. Aquí el gazetteer se repite.

    **La regla del código, en cambio, sólo una vez**, como en el cuaderno: tras sustituir, detrás
    del código queda el propio marcador, y el marcador más un nombre «parece un nombre» —seis
    palabras, ninguna de STOP—, así que repetirla juntaba a dos personas en un solo marcador.
    """
    if not isinstance(desc, str) or not desc.strip():
        return desc
    desc, _ = _anon_codi(desc)
    for _ in range(10):
        nou, tram = _anon_gazetteer(desc, idx)
        if not tram or nou == desc:
            return desc
        desc = nou
    return desc


def _lineas(ruta):
    # El auditor no deja abrir ficheros a mano: un fichero de texto se lee con una librería. El
    # separador es un carácter de control que el texto no lleva, para que cada línea sea una fila
    # entera.
    tabla = pd.read_csv(ruta, header=None, names=["linea"], sep="\x1f", quoting=3, dtype=str,
                        keep_default_na=False, encoding="utf-8-sig", skip_blank_lines=True)
    return tabla["linea"].tolist()


rutas = options["ficheros"]
pdi = build_pdi_index(_lineas(rutas["pdi"]))
df = pd.read_csv(rutas["presupuesto"], dtype=str, keep_default_na=False, encoding="utf-8-sig")

redacciones = 0
for col in COLUMNAS_DE_TEXTO:
    if col in df.columns:
        nuevas = df[col].apply(lambda x: anonimitza_text(x, pdi))
        redacciones += int((nuevas != df[col]).sum())
        df[col] = nuevas

# El tercero: en los gastos puede ser una persona; en los ingresos es la entidad que financia.
es_gasto = df["Pcr Apl Tipo"].eq("P") if "Pcr Apl Tipo" in df.columns else pd.Series(False, index=df.index)
if "Tercero Nombre" in df.columns:
    nuevos = df["Tercero Nombre"].where(
        ~es_gasto, df["Tercero Nombre"].apply(lambda x: anonimitza_text(x, pdi))
    )
    redacciones += int((nuevos != df["Tercero Nombre"]).sum())
    df["Tercero Nombre"] = nuevos
nif_vaciados = 0
if "Tercero Nif" in df.columns:
    nif_vaciados = int((es_gasto & df["Tercero Nif"].ne("")).sum())
    df.loc[es_gasto, "Tercero Nif"] = ""

df.to_csv(output_dir + "/presupuesto_anonimizado.csv", index=False, encoding="utf-8-sig")

result = {
    "metrics": [
        {"name": "filas", "value": len(df)},
        {"name": "nombres_en_el_pdi", "value": len(pdi)},
        {"name": "redacciones", "value": redacciones},
        {"name": "nif_de_gastos_vaciados", "value": nif_vaciados},
    ]
}
