"""APER.17 — la puerta de avisos dice de qué conjunto habla.

**El problema, medido el 2026-09-19.** Dependabot informó de avisos críticos en `server/uv.lock`
mientras el job `supply-chain` estaba **en verde**. No era un desacuerdo entre bases de datos: OSV
conocía los catorce avisos de `authlib`. Era el **alcance**. `uv export --no-dev` sin
`--all-extras` exporta sólo las dependencias base: **200 paquetes de los 438** que describe el
lock. Y los seis paquetes avisados —`authlib`, `httplib2`, `mcp`, `transformers`, `torch`,
`pytest`— entran por extras (`agente-navegador`, `local-models`) o por el grupo `dev`.

Auditar lo que se despliega es **defendible**: es lo que corre. Lo que no es defendible es que el
verde no diga su alcance, porque quien lo lea concluirá que el lock está limpio. Y hubo una
consecuencia concreta: al cerrar las PR de seguridad, Dependabot dejó de recordar esas versiones,
y el único recordatorio que quedaba era una lista de alertas en una pestaña.

**El arreglo: dos conjuntos en el mismo paso.** El desplegado **bloquea** —es lo que corre en
producción— y el completo **informa**, restándole el desplegado para que la sección diga lo que
importa: «esto lo trae el lock y el despliegue no lo instala». Así el recordatorio vive donde lo
controlamos y no depende de que un robot se acuerde.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
GUION = RAIZ / "scripts" / "puerta_de_avisos.py"


def _informe(ruta: Path, avisos: list[tuple[str, str, str, list[str]]]) -> Path:
    """Un JSON con la forma que emite `pip-audit`."""
    ruta.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": nombre,
                        "version": version,
                        "vulns": [{"id": vid, "fix_versions": arreglos}],
                    }
                    for nombre, version, vid, arreglos in avisos
                ]
            }
        ),
        encoding="utf-8",
    )
    return ruta


def _aceptados_vacio(ruta: Path) -> Path:
    ruta.write_text("# sin aceptaciones\n", encoding="utf-8")
    return ruta


def _correr(*argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUION), *argumentos],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class TestLoDesplegadoBloquea:

    def test_un_aviso_con_correccion_en_lo_desplegado_pone_rojo(self, tmp_path: Path) -> None:
        desplegado = _informe(
            tmp_path / "desplegado.json", [("uvicorn", "0.40.0", "PYSEC-X", ["0.41.0"])]
        )
        res = _correr(
            str(desplegado), "--aceptados", str(_aceptados_vacio(tmp_path / "a.toml"))
        )
        assert res.returncode == 1, res.stdout
        assert "BLOQUEA" in res.stdout


class TestLoQueSoloEstaEnElLockInforma:

    def test_un_aviso_de_un_extra_no_bloquea(self, tmp_path: Path) -> None:
        """`authlib` entra por `agente-navegador`, que el despliegue no instala."""
        desplegado = _informe(tmp_path / "desplegado.json", [])
        completo = _informe(
            tmp_path / "completo.json", [("authlib", "1.6.6", "GHSA-AUTH", ["1.6.12"])]
        )

        res = _correr(
            str(desplegado),
            "--informativos", str(completo),
            "--aceptados", str(_aceptados_vacio(tmp_path / "a.toml")),
        )

        assert res.returncode == 0, f"un aviso fuera del despliegue no puede bloquear: {res.stdout}"
        assert "authlib" in res.stdout, "y tampoco puede desaparecer del informe"

    def test_se_dice_que_no_esta_en_el_despliegue(self, tmp_path: Path) -> None:
        """La frase es el arreglo: sin ella, el verde sigue sin decir su alcance."""
        completo = _informe(
            tmp_path / "completo.json", [("authlib", "1.6.6", "GHSA-AUTH", ["1.6.12"])]
        )
        res = _correr(
            str(_informe(tmp_path / "d.json", [])),
            "--informativos", str(completo),
            "--aceptados", str(_aceptados_vacio(tmp_path / "a.toml")),
        )
        # Se busca el encabezado, no una frase suelta: es lo que ve quien lee el resumen de un
        # run, y no se rompe por reescribir la explicación de debajo.
        assert "fuera del despliegue" in res.stdout, res.stdout
        # Y que el encabezado del bloque que sí bloquea diga también su alcance.
        assert "que se despliega" in res.stdout, res.stdout

    def test_no_se_repite_lo_que_ya_bloquea(self, tmp_path: Path) -> None:
        """El conjunto completo **contiene** al desplegado: sin restar, cada aviso saldría dos
        veces y el informe engañaría sobre cuántos hay."""
        aviso = ("uvicorn", "0.40.0", "PYSEC-X", ["0.41.0"])
        res = _correr(
            str(_informe(tmp_path / "d.json", [aviso])),
            "--informativos", str(_informe(tmp_path / "c.json", [aviso])),
            "--aceptados", str(_aceptados_vacio(tmp_path / "a.toml")),
        )
        assert res.stdout.count("PYSEC-X") == 1, (
            f"el mismo aviso sale más de una vez:\n{res.stdout}"
        )


class TestElInformeQueFaltaSigueSiendoUnFallo:
    """La lección de la primera ejecución: un informe ausente no es «cero avisos»."""

    def test_un_informativo_que_falta_pone_rojo(self, tmp_path: Path) -> None:
        res = _correr(
            str(_informe(tmp_path / "d.json", [])),
            "--informativos", str(tmp_path / "no-existe.json"),
            "--aceptados", str(_aceptados_vacio(tmp_path / "a.toml")),
        )
        assert res.returncode == 1
        assert "no llegó a ejecutarse" in res.stdout or "Falta el informe" in res.stdout


class TestElAuditorDelLockLeeLoQueTieneQueLeer:
    """`avisos_del_lock.py` — el que pregunta a OSV por lotes.

    **Por qué no es `pip-audit` aquí.** Medido el 2026-09-19: `pip-audit -r` sobre los 435
    paquetes del lock de `server` pasó de quince minutos sin producir informe, porque **instala**
    lo que lee para resolverlo y ahí están las ruedas de `torch`. Por OSV, 14 segundos y los
    mismos diez paquetes que reporta Dependabot. Para el conjunto desplegado se sigue pagando
    `pip-audit`, que da la resolución de verdad sobre 200 paquetes.
    """

    @staticmethod
    def _paquetes(texto: str, tmp_path: Path) -> dict[str, str]:
        import importlib.util

        ruta = RAIZ / "scripts" / "avisos_del_lock.py"
        spec = importlib.util.spec_from_file_location("avisos_del_lock", ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)

        fichero = tmp_path / "req.txt"
        fichero.write_text(texto, encoding="utf-8")
        return modulo.paquetes_de(fichero)

    def test_lee_los_pinchados_e_ignora_lo_demas(self, tmp_path: Path) -> None:
        texto = "\n".join(
            [
                "# un comentario",
                "uvicorn==0.40.0",
                "    # via fastapi",
                "pydantic[email]==2.12.5",
                "torch==2.11.0+cpu ; sys_platform != 'darwin'",
                "-e ./tests/fixtures/paquete_perfil_demo",
                "--index-url https://example.invalid",
                "",
            ]
        )
        assert self._paquetes(texto, tmp_path) == {
            "uvicorn": "0.40.0",
            "pydantic": "2.12.5",
            "torch": "2.11.0+cpu",
        }

    def test_un_export_vacio_no_es_cero_avisos(self, tmp_path: Path) -> None:
        """Escribir un informe vacío sería el fichero que parece bueno y mide otra cosa."""
        vacio = tmp_path / "vacio.txt"
        vacio.write_text("# nada\n", encoding="utf-8")
        res = subprocess.run(
            [sys.executable, str(RAIZ / "scripts" / "avisos_del_lock.py"),
             str(vacio), "--salida", str(tmp_path / "s.json")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False,
        )
        assert res.returncode == 1, res.stdout
        assert not (tmp_path / "s.json").exists(), "ha escrito un informe de un export vacío"


class TestElJobExportaLosDosConjuntos:
    """Y el workflow tiene que pedirlos, o el guion no los recibe."""

    # `staticmethod` porque `pytest` 9.1 deprecó las *fixtures* de ámbito de clase declaradas
    # como método de instancia, y ésta no usa `self`.
    @staticmethod
    @pytest.fixture(scope="class")
    def paso_export() -> str:
        import yaml

        ci = yaml.safe_load((RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
        for paso in ci["jobs"]["supply-chain"]["steps"]:
            if "Export" in (paso.get("name") or ""):
                return paso["run"]
        raise AssertionError("no encuentro el paso de export")

    def test_exporta_tambien_el_conjunto_completo(self, paso_export: str) -> None:
        assert "--all-extras" in paso_export, (
            "El job no exporta el conjunto completo del lock, así que sigue auditando 200 "
            "paquetes de 438 sin decirlo."
        )

    def test_el_guion_recibe_los_informativos(self) -> None:
        import yaml

        ci = yaml.safe_load((RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
        puerta = next(
            paso["run"]
            for paso in ci["jobs"]["supply-chain"]["steps"]
            if "Vulnerability gate" in (paso.get("name") or "")
        )
        assert "--informativos" in puerta, (
            "La puerta no recibe los informes del conjunto completo: se exportarían y nadie "
            "los leería, que es el fichero en el artefacto y el aviso sin mirar."
        )
