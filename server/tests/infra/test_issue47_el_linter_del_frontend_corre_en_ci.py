"""El linter del frontend corre en CI, bloquea, y su techo no sube solo (issue #47).

**El hueco.** `npm run lint` existía y **no lo llamaba ningún trabajo del workflow**. Un linter
configurado que no corre en CI es un linter apagado: avisa sólo a quien se acuerda de ejecutarlo
en local. El backend sí se linteaba (`ruff check app/ tests/`); ésta era la mitad que faltaba.

**Lo que se midió antes de decidir nada**, y es lo que hizo el reparto obvio:

| Clase | Cuántos | Dónde |
|---|---|---|
| `no-explicit-any` | 61 | **Todos en tests**, cero en producción |
| Fast Refresh e informativos del compilador | 13 | Producción, y **no son defectos** |
| `set-state-in-effect`, `exhaustive-deps`, `refs` | 20 | Producción, y **sí lo son** |

Los 74 primeros se resolvieron **configurando**, con su razón escrita en `eslint.config.js`. Los
20 restantes cambian comportamiento en tiempo de ejecución y están repartidos en 15 componentes:
arreglarlos es un bloque propio con verificación en navegador, no un efecto colateral de encender
el linter.

**Por qué un techo y no `0`.** Con el techo, un hallazgo **nuevo** tumba el job aunque los viejos
sigan ahí. Sin él habría que elegir entre no encender nada o arreglar veinte defectos a ciegas.
Lo que este fichero vigila es justamente lo que hace peligroso un techo: **que suba en silencio**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
CI = RAIZ / ".github" / "workflows" / "ci.yml"
PACKAGE = RAIZ / "frontend" / "package.json"
CONFIG = RAIZ / "frontend" / "eslint.config.js"

#: El techo de hoy. Subirlo exige cambiarlo **aquí también**, que es la conversación que se
#: quiere tener: un número que crece solo deja de significar nada.
#:
#: **Y baja con cada arreglo, en su mismo commit** (issue #111). Un techo que sólo se defiende de
#: subidas acaba siendo el número con el que se convive.
#:
#: · 33 → 26 el 2026-09-27: `ThemeProvider`, `useAutosave`, `ThemeEditor`.
#: · 26 → 23 el 2026-09-27: `ActivityPromptsPage`, `ValoresPorDefectoPage`.
TECHO = 23


def _script_lint() -> str:
    return json.loads(PACKAGE.read_text(encoding="utf-8"))["scripts"]["lint"]


def _pasos_que_lintean() -> list[dict]:
    datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return [
        paso
        for cuerpo in datos["jobs"].values()
        for paso in cuerpo.get("steps", [])
        if "npm run lint" in (paso.get("run") or "")
    ]


class TestElLinterCorreYBloquea:
    def test_algun_trabajo_lo_ejecuta(self) -> None:
        assert _pasos_que_lintean(), (
            "ningún trabajo de CI ejecuta `npm run lint`: el linter está configurado y apagado, "
            "que es como estaba antes de la issue #47"
        )

    def test_no_se_le_perdona_el_fallo(self) -> None:
        """`continue-on-error` lo dejaría informando sin parar nada, que es no encenderlo."""
        perdonados = [p.get("name") for p in _pasos_que_lintean() if p.get("continue-on-error")]
        assert perdonados == [], (
            f"el paso del linter lleva `continue-on-error`: {perdonados}. Informa y no bloquea, "
            "así que un hallazgo nuevo pasaría igual."
        )

    def test_corre_donde_el_cliente_generado_existe(self) -> None:
        """Orval genera el cliente y **no viaja en el repositorio**.

        Si el linter corriera en un trabajo que no lo genera, se encontraría imports rotos: el
        fallo no sería del código sino del orden, y el mensaje no lo diría.
        """
        datos = yaml.safe_load(CI.read_text(encoding="utf-8"))
        for nombre, cuerpo in datos["jobs"].items():
            pasos = cuerpo.get("steps", [])
            corre = [i for i, p in enumerate(pasos) if "npm run lint" in (p.get("run") or "")]
            if not corre:
                continue
            genera = [
                i for i, p in enumerate(pasos) if "generate:api" in (p.get("run") or "")
            ]
            assert genera and min(genera) < min(corre), (
                f"el trabajo «{nombre}» lintea sin generar antes el cliente de la API"
            )


class TestElTechoNoSubeSolo:
    def test_el_script_declara_el_techo(self) -> None:
        encontrado = re.search(r"--max-warnings\s+(\d+)", _script_lint())
        assert encontrado, (
            f"el script `lint` no fija `--max-warnings`: «{_script_lint()}». Sin techo, los "
            "avisos crecen sin que nada lo pare."
        )

    def test_el_techo_es_el_declarado_aqui(self) -> None:
        """Subirlo obliga a tocar este fichero, que es toda la gracia."""
        encontrado = re.search(r"--max-warnings\s+(\d+)", _script_lint())
        assert encontrado and int(encontrado.group(1)) == TECHO, (
            f"el script fija el techo en {encontrado.group(1) if encontrado else '—'} y aquí "
            f"está declarado {TECHO}. Si de verdad ha bajado, actualiza los dos; si ha **subido**, "
            "es que se han colado hallazgos nuevos y eso es lo que el techo venía a impedir."
        )

    def test_las_reglas_del_techo_siguen_encendidas_como_aviso(self) -> None:
        """Ponerlas en `off` vaciaría el techo sin bajar ni un defecto."""
        texto = CONFIG.read_text(encoding="utf-8")
        for regla in (
            "react-hooks/set-state-in-effect",
            "react-hooks/exhaustive-deps",
            "react-hooks/refs",
        ):
            assert f"'{regla}': 'warn'" in texto, (
                f"la regla `{regla}` ya no está como aviso en `eslint.config.js`. Si se ha "
                "apagado, el techo de 33 deja de contar lo que decía contar."
            )

    def test_el_any_solo_se_perdona_en_tests(self) -> None:
        """Lo que hace honesta la exención: producción tenía **cero**, y así sigue."""
        # Posicional y no por corte en la primera mención: el comentario que explica la regla la
        # nombra **antes** del bloque, así que `split(...)[0]` se quedaba con el comentario.
        texto = CONFIG.read_text(encoding="utf-8")
        apagado = texto.find("'@typescript-eslint/no-explicit-any': 'off'")
        assert apagado != -1, "`no-explicit-any` ya no se apaga en ninguna parte"

        acotado = texto.rfind("__tests__", 0, apagado)
        assert acotado != -1, (
            "`no-explicit-any` se apaga sin acotarlo a los ficheros de test. Esa exención se "
            "escribió porque los 61 hallazgos estaban todos en tests y producción tenía cero; "
            "extenderla a producción sería otra cosa."
        )
        assert "*.test." in texto[acotado:apagado] or "*.test." in texto[
            max(0, acotado - 200) : apagado
        ], "la exención no cubre los `*.test.tsx`, que también son tests"
