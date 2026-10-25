"""APER.13 — el DCO exime a los robots, y la exención no se puede ensanchar sin que se note.

**Por qué existe la exención.** El DCO certifica «I have the right to submit it under the open
source license indicated in the file». Eso lo afirma **una persona** sobre código que aporta. Un
robot que sube un número de versión en un `uv.lock` no aporta código de nadie: reordena una
resolución de dependencias. No hay autoría que certificar.

Y exigírselo tenía un coste medido: el 2026-09-19 había **trece pull requests de Dependabot
abiertas a la vez y ninguna se podía mezclar**, todas en rojo por la misma línea. Un guardarraíl
que hace imposible el camino bueno se acaba apagando entero, y eso sí habría sido perder el DCO.

**Qué vigila este fichero.** Que la exención sea exactamente la que se decidió: por **correo** del
autor y sólo para cuentas de robot, que se **diga en el registro** cuando se aplica, y que para
las personas no cambie nada. Lo último es lo que importa: la política sigue valiendo para el
mantenedor —quien se exceptúa de su propia política la deja sin fuerza— y por eso no vale
comprobar el nombre, que lo puede poner cualquiera en un commit.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
DCO = RAIZ / ".github" / "workflows" / "dco.yml"


@pytest.fixture(scope="module")
def guion() -> str:
    """El guion del paso que comprueba las firmas."""
    datos = yaml.safe_load(DCO.read_text(encoding="utf-8"))
    pasos = datos["jobs"]["signed-off-by"]["steps"]
    for paso in pasos:
        if "Signed-off-by" in (paso.get("name") or ""):
            return paso["run"]
    raise AssertionError("no encuentro el paso que comprueba el Signed-off-by")


class TestLaExencionEsLaQueSeDecidio:

    # Aquí estuvo `test_se_exime_por_correo_y_no_por_nombre`, y **su premisa era falsa**.
    # Decía: «el nombre de autor lo elige quien commitea; el correo de la cuenta, no», y exigía
    # que la exención mirase el correo contra `*[bot]@users.noreply.github.com`. Pero el correo
    # del autor lo elige quien commitea **exactamente igual** que el nombre: basta un
    # `git config user.email`. O sea que el test no vigilaba un agujero, **lo fijaba**.
    #
    # Lo retiró **APER.26**, que estrechó la exención a una lista exacta. Lo que comprueba
    # ahora que sigue siendo una exención y no un agujero es
    # `test_aper26_la_exencion_del_dco_no_es_un_comodin.py`, que **ejecuta** el guion contra un
    # repositorio de prueba con un commit de impostor. Un test que mira si una cadena está en
    # un fichero no podía distinguir los dos casos, porque la cadena era la misma.

    def test_la_exencion_es_una_lista_cerrada(self, guion: str) -> None:
        """Lo que sí se puede leer del texto: que no haya vuelto un comodín.

        Es un aviso temprano y barato, no la comprobación de verdad — ésa ejecuta el guion en
        APER.26. Vale la pena porque un comodín se reintroduce en una línea y se lee igual de
        bien que una lista.
        """
        assert "ROBOTS_EXENTOS" in guion, (
            "la exención ya no sale de una lista con nombre, así que no se puede leer de un "
            "vistazo a quién exime"
        )
        assert '== *"[bot]@' not in guion, (
            "ha vuelto un comodín sobre el correo del autor. Eso no exime a un robot: exime a "
            "cualquiera que escriba ese correo, y escribirlo es un `git config`."
        )

    def test_la_exencion_se_dice_en_el_registro(self, guion: str) -> None:
        """Una exención que no se ve en el registro es una que nadie vuelve a revisar."""
        assert "::notice::" in guion, "Cuando se salta un commit, el paso tiene que decirlo en el registro."
        assert "exento" in guion, "Cuando se salta un commit, el paso tiene que decirlo en el registro."

    def test_los_saltados_se_cuentan_aparte(self, guion: str) -> None:
        """Sumarlos a los revisados haría que el resumen dijera «todos firmados» de commits
        que nadie ha comprobado."""
        assert "saltados" in guion, "no se lleva cuenta de los commits exentos"
        assert "saltados=$((saltados + 1))" in guion


class TestParaLasPersonasNoCambiaNada:

    def test_sigue_exigiendo_la_firma(self, guion: str) -> None:
        assert "Signed-off-by:" in guion, "El paso ha dejado de exigir la firma."
        assert "falta Signed-off-by" in guion, "El paso ha dejado de exigir la firma."

    def test_sigue_exigiendo_que_la_firma_sea_del_autor(self, guion: str) -> None:
        """Firmar con el nombre de otro no certifica nada."""
        assert "no coincide con el autor" in guion

    def test_sigue_poniendose_rojo(self, guion: str) -> None:
        assert "exit 1" in guion, "el paso ya no falla cuando encuentra un commit sin firmar"

    def test_sigue_revisando_las_dos_ramas_y_las_pull_requests(self) -> None:
        """La política vale para `main` y `desarrollo`, y eso no lo toca APER.13.

        **Este test fijaba `pull_request: [main]` y se amplió el 2026-09-20.** No porque la
        política cambiara, sino porque así escrita dejaba fuera justo a quien esta exención
        existe para desbloquear: Dependabot abre sus PR contra `desarrollo`, y sin ese
        disparador **no se le ejecutaba el DCO ni ninguna otra cosa**. Había veinte PR suyas
        con cero comprobaciones. Lo vigila
        `test_las_pr_a_desarrollo_tambien_se_comprueban.py`, que saca la lista de ramas del
        propio `dependabot.yml` en vez de escribirla a mano.
        """
        datos = yaml.safe_load(DCO.read_text(encoding="utf-8"))
        disparadores = datos[True] if True in datos else datos["on"]
        assert set(disparadores["push"]["branches"]) == {"main", "desarrollo"}
        assert set(disparadores["pull_request"]["branches"]) == {"main", "desarrollo"}


class TestLaRazonEstaEscrita:

    def test_el_fichero_explica_por_que_se_exime(self) -> None:
        """Sin la razón, dentro de un año esto parece un atajo que alguien metió con prisa."""
        prosa = " ".join(
            linea.lstrip("# ").strip()
            for linea in DCO.read_text(encoding="utf-8").splitlines()
            if linea.lstrip().startswith("#")
        )
        prosa = " ".join(prosa.split())
        for idea in ("robot", "certific", "responsabilidad"):
            assert idea in prosa, f"la razón de la exención no menciona «{idea}»"

    def test_contributing_lo_cuenta(self) -> None:
        """Quien contribuye lee `CONTRIBUTING.md`, no el YAML del workflow."""
        texto = (RAIZ / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "dependabot" in texto.lower(), (
            "`CONTRIBUTING.md` no menciona la exención: quien lea que «cada commit va firmado» "
            "y vea un commit de robot sin firmar en el historial pensará que la política no se "
            "cumple."
        )
