"""El catálogo del producto viaja como ficheros, no como filas (D.7).

La distinción que este prompt separa, y que es el fondo del asunto: **el catálogo que acompaña
al producto y los datos operativos del cliente viajan de forma distinta.**

- Las plantillas demo se exportan a `app/data/plantillas_demo/` y las siembra
  `bootstrap.py --con-demo`. Así la demo es reproducible, se revisa en un diff y es la misma en
  todos los despliegues. Es la regla que ya rige el vocabulario del corpus.
- El corpus, la curación y los chatbots van por `scripts/volcado_piloto.sh`.

Confundirlas es lo que dejaba la pregunta «¿qué pasa al piloto?» sin buena respuesta: un
volcado completo se lleva los 29 informes de prueba, y empezar de cero tira el trabajo humano.

**La lista es explícita y vive en el código.** En la base de desarrollo hay más de veinte
plantillas y casi todas son basura de verificación (`PRO4 …`, `Plantilla prueba Camino3 repro3`).
Deducir cuáles son demo por `is_global` o por la fecha las arrastraría.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.app.scripts.exportar_plantillas_demo import (
    A_BORRAR,
    CATALOGO,
    a_documento,
    esta_vacia,
)

RAIZ = Path(__file__).resolve().parents[3]
DATOS = RAIZ / "server" / "app" / "data" / "plantillas_demo"


# ---------------------------------------------------------------------------
# La lista
# ---------------------------------------------------------------------------


def test_el_catalogo_es_explicito_y_cada_entrada_dice_por_que() -> None:
    assert CATALOGO, "El catálogo está vacío."
    for plantilla in CATALOGO:
        assert plantilla.razon.strip(), f"{plantilla.nombre_origen} no dice por qué está"
        assert plantilla.fichero.endswith(".json")


def test_no_se_exporta_nada_que_no_este_en_la_lista() -> None:
    """Los ficheros de datos son exactamente los declarados, ni uno más.

    Si apareciera un `PRO4 plantilla con transformacion.json`, alguien habría exportado a mano
    y el catálogo del producto dejaría de ser lo que dice el código.
    """
    # **Sin `skip` si la carpeta no está.** Este `pytest.skip` —y el de
    # `test_lo_exportado_tiene_contenido_y_no_un_spec_vacio`— dejaban el fichero **en verde sin
    # comprobar nada en CI**, porque `.gitignore` excluía `server/app/data/` de rebote con su
    # `data/` y los ficheros nunca llegaban al checkout. Meses así: el guardarraíl que debía
    # vigilar el catálogo se saltaba a sí mismo justo donde hacía falta, y nadie lo notó hasta que
    # un test del issue #84 **afirmó** en vez de saltar. Ahora los ficheros están versionados, así
    # que no estar es un defecto y se dice.
    assert DATOS.is_dir(), (
        f"no existe {DATOS}. Las plantillas demo están versionadas desde el 2026-09-21: si no "
        "están en el árbol, `bootstrap --con-demo` no puede sembrar nada en ningún despliegue."
    )
    declarados = {p.fichero for p in CATALOGO}
    presentes = {f.name for f in DATOS.glob("*.json")}
    de_mas = presentes - declarados
    assert not de_mas, f"Ficheros que no están en el catálogo: {sorted(de_mas)}"


def test_la_plantilla_vacia_esta_marcada_para_borrar_y_no_para_exportar() -> None:
    """`Ejecucion presupuestaria trimestral` son 2 bytes: `{}`."""
    nombres_a_borrar = {n for n, _ in A_BORRAR}
    assert "Ejecucion presupuestaria trimestral" in nombres_a_borrar
    assert "Ejecucion presupuestaria trimestral" not in {p.nombre_origen for p in CATALOGO}
    for _, razon in A_BORRAR:
        assert razon.strip(), "Un borrado sin razón escrita es un DELETE a mano con otro nombre"


def test_la_que_se_renombra_dice_de_que_a_que() -> None:
    """`GUI3` es el nombre de un prompt de verificación, no de un producto."""
    renombradas = [p for p in CATALOGO if p.nombre_publicado != p.nombre_origen]
    assert renombradas, "Se esperaba al menos una plantilla renombrada"
    for plantilla in renombradas:
        assert "GUI3" not in plantilla.nombre_publicado
        assert plantilla.razon, "El renombrado tiene que estar justificado"


# ---------------------------------------------------------------------------
# La guarda del spec vacío
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "vacia"),
    [
        ({}, True),
        (None, True),
        ("{}", True),
        ([], True),
        ({"blocks": []}, False),
        ({"titulo": "x"}, False),
    ],
)
def test_reconoce_un_spec_vacio(spec, vacia) -> None:
    """Sembrar un `{}` da una plantilla que se abre y no tiene nada dentro, y el fallo
    aparecería en el piloto y no aquí."""
    assert esta_vacia(spec) is vacia


# ---------------------------------------------------------------------------
# Todas las versiones, no sólo la vigente
# ---------------------------------------------------------------------------


class _FilaFalsa:
    def __init__(self, current_version_id=None):
        self.description = "descripción"
        self.report_profile = "seguimiento"
        self.current_version_id = current_version_id


class _VersionFalsa:
    def __init__(self, id_, version, spec):
        self.id = id_
        self.version = version
        self.spec_json = spec


def test_el_documento_lleva_todas_las_versiones() -> None:
    """Una plantilla sin historial no se puede revertir, y el versionado del módulo es
    append-only precisamente para eso."""
    versiones = [
        _VersionFalsa("v1", 1, {"blocks": ["a"]}),
        _VersionFalsa("v2", 2, {"blocks": ["a", "b"]}),
    ]
    documento = a_documento(CATALOGO[0], _FilaFalsa(current_version_id="v2"), versiones)
    assert [v["version"] for v in documento["versiones"]] == [1, 2]
    assert documento["version_vigente"] == 2
    assert documento["nombre"] == CATALOGO[0].nombre_publicado
    assert documento["nombre_origen"] == CATALOGO[0].nombre_origen


def test_el_documento_conserva_el_spec_tal_cual() -> None:
    """Round-trip: lo que se exporta es lo que se sembrará."""
    spec = {"blocks": [{"type": "TABLE", "id": "t1"}], "titulo": "Informe"}
    documento = a_documento(CATALOGO[0], _FilaFalsa("v1"), [_VersionFalsa("v1", 1, spec)])
    ida_y_vuelta = json.loads(json.dumps(documento, ensure_ascii=False))
    assert ida_y_vuelta["versiones"][0]["spec_json"] == spec


# ---------------------------------------------------------------------------
# Lo exportado de verdad
# ---------------------------------------------------------------------------


def test_lo_exportado_tiene_contenido_y_no_un_spec_vacio() -> None:
    ficheros = sorted(DATOS.glob("*.json")) if DATOS.is_dir() else []
    # Por lo mismo que arriba: si no hay ficheros, eso **es** el hallazgo.
    assert ficheros, (
        f"no hay ninguna plantilla demo en {DATOS}, y están versionadas: sin ellas la siembra "
        "del catálogo no hace nada"
    )
    for fichero in ficheros:
        documento = json.loads(fichero.read_text(encoding="utf-8"))
        assert documento["versiones"], f"{fichero.name} no tiene versiones"
        for version in documento["versiones"]:
            assert not esta_vacia(version["spec_json"]), (
                f"{fichero.name} v{version['version']} tiene el spec vacío"
            )
        assert documento["report_profile"], f"{fichero.name} sin perfil"


def test_el_sembrado_lee_los_ficheros_y_no_la_base_de_nadie() -> None:
    bootstrap = (RAIZ / "server" / "app" / "scripts" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "plantillas_demo" in bootstrap, "El sembrado tiene que leer los ficheros del catálogo"
    assert "--con-demo" in bootstrap, "Falta el interruptor explícito"
    # Idempotencia por nombre, y sin actualizar la existente.
    assert "if existente is not None:" in bootstrap, "El sembrado tiene que ser idempotente y no pisar una plantilla que alguien ya usó"
    assert "return False" in bootstrap, "El sembrado tiene que ser idempotente y no pisar una plantilla que alguien ya usó"
