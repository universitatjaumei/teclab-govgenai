"""APER.23 — dos sitios donde el auditor de avisos podía mentir sin dar error.

Los dos los encontró la revisión automática de la PR #50, y los dos son la misma avería con
distinto disfraz: **una respuesta que falta se confunde con una respuesta que dice «no hay
nada»**. Es la forma de fallo que este proyecto ya tiene nombrada, «el medidor miente antes que
el sistema», y aquí duele el doble porque lo que el medidor decide es si CI bloquea.

**1. Un fallo de red se leía como «no hay corrección publicada».** `avisos_del_lock._arreglos`
pregunta a OSV por las versiones que corrigen cada aviso, y envolvía la llamada en un
`except (URLError, TimeoutError): return []`. La lista vacía es exactamente el valor que
significa «este aviso no tiene arreglo», y ése es el valor con el que la puerta decide entre
bloquear e informar. O sea que un OSV lento un martes convertía un aviso **corregible** en uno
**incorregible**, el informe salía en verde y nadie tenía por qué enterarse. El propio docstring
de la función decía que ese dato «es justo lo que no se puede aproximar», y lo aproximaba.

Ahora el fallo **se propaga**: el guion se cae, CI se pone rojo y alguien vuelve a lanzarlo. Un
auditor que no ha podido auditar tiene que decirlo, no entregar un informe optimista.

**2. La resta del informe usaba una clave más corta que la que agrupa.** `lee_informe` deduplica
por `(paquete, id)` —a propósito: `pip-audit` repite la pareja cuando un paquete entra por varios
caminos— pero el informe restaba el conjunto desplegado del completo **sólo por `id`**. Un mismo
identificador puede afectar a **dos paquetes distintos**; cuando eso pasa, encontrarlo en el
desplegado borraba también al otro paquete de la lista informativa, que desaparecía en silencio.
Se resta con la misma clave con la que se agrupa.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
GUIONES = RAIZ / "scripts"

if str(GUIONES) not in sys.path:  # los guiones no son un paquete instalable
    sys.path.insert(0, str(GUIONES))

import avisos_del_lock  # noqa: E402
import puerta_de_avisos  # noqa: E402


class TestUnFalloDeRedNoEsUnaRespuesta:
    """Que OSV no conteste no puede parecerse a que conteste «no hay arreglo»."""

    def test_un_fallo_de_red_se_propaga(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _cae(*_args: object, **_kwargs: object):
            raise urllib.error.URLError("OSV no responde")

        monkeypatch.setattr(avisos_del_lock.urllib.request, "urlopen", _cae)

        with pytest.raises(urllib.error.URLError, match="OSV no responde") as fallo:
            avisos_del_lock._arreglos("PYSEC-2026-3447", "setuptools")

        assert not isinstance(fallo.value, AssertionError), (
            "la consulta devolvió en vez de fallar: un aviso corregible se informaría como "
            "incorregible y la puerta lo dejaría pasar."
        )

    def test_una_respuesta_buena_sigue_dando_las_versiones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El camino bueno, comprobado: donde hay un `except` hace falta probar los dos lados."""
        detalle = {
            "affected": [
                {
                    "package": {"name": "setuptools"},
                    "ranges": [{"events": [{"introduced": "0"}, {"fixed": "83.0.0"}]}],
                },
                {  # otro paquete en el mismo aviso: no es nuestro y no cuenta
                    "package": {"name": "otra-cosa"},
                    "ranges": [{"events": [{"fixed": "1.2.3"}]}],
                },
            ]
        }

        class _Respuesta:
            def read(self) -> bytes:
                return json.dumps(detalle).encode()

            def __enter__(self) -> "_Respuesta":
                return self

            def __exit__(self, *_: object) -> None:
                return None

        monkeypatch.setattr(
            avisos_del_lock.urllib.request, "urlopen", lambda *a, **k: _Respuesta()
        )
        assert avisos_del_lock._arreglos("PYSEC-2026-3447", "setuptools") == ["83.0.0"]


class TestLaRestaUsaLaMismaClaveQueElAgrupado:
    """Un identificador puede afectar a dos paquetes, y entonces la clave corta pierde uno."""

    def test_el_mismo_id_en_dos_paquetes_no_se_traga_al_otro(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        desplegado = _informe(tmp_path / "desplegado.json", [("uno", "1.0", "GHSA-x", [])])
        completo = _informe(
            tmp_path / "completo.json",
            [("uno", "1.0", "GHSA-x", []), ("dos", "2.0", "GHSA-x", [])],
        )
        aceptados = tmp_path / "aceptados.toml"
        aceptados.write_text("", encoding="utf-8")
        resumen = tmp_path / "resumen.md"

        codigo = puerta_de_avisos.main(
            [
                str(desplegado),
                "--informativos", str(completo),
                "--aceptados", str(aceptados),
                "--resumen", str(resumen),
            ]
        )
        assert codigo == 0, "ninguno de los dos avisos tiene corrección: no debería bloquear"

        texto = resumen.read_text(encoding="utf-8") + capsys.readouterr().out
        assert "dos" in texto, (
            "el aviso del paquete `dos` ha desaparecido del informe. Comparte identificador con "
            "el de `uno`, que sí está en el conjunto desplegado, y la resta por `id` a secas se "
            "lo llevó por delante: un paquete afectado que nadie ve."
        )


def _informe(destino: Path, filas: list[tuple[str, str, str, list[str]]]) -> Path:
    """Un informe con la forma que emite `pip-audit --format json`."""
    destino.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": nombre,
                        "version": version,
                        "vulns": [{"id": vid, "fix_versions": arreglos}],
                    }
                    for nombre, version, vid, arreglos in filas
                ]
            }
        ),
        encoding="utf-8",
    )
    return destino


class TestElEmparejadoPorPosicion:
    """`main` empareja consultas y resultados con `zip`, y eso hay que comprobarlo.

    Si OSV devolviera menos resultados que consultas, `zip` se pararía en el más corto **sin
    decir nada** y cada aviso quedaría colgado del paquete equivocado. Un informe que acusa a
    `jinja2` de lo de `torch` tiene el mismo aspecto que uno bueno.
    """

    @staticmethod
    def _requirements(destino: Path, paquetes: list[tuple[str, str]]) -> Path:
        destino.write_text(
            "\n".join(f"{n}=={v}" for n, v in paquetes) + "\n", encoding="utf-8"
        )
        return destino

    def test_cada_aviso_queda_en_su_paquete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El camino bueno: tres paquetes, el aviso es del de en medio."""
        entrada = self._requirements(
            tmp_path / "req.txt", [("uno", "1.0"), ("dos", "2.0"), ("tres", "3.0")]
        )
        monkeypatch.setattr(
            avisos_del_lock,
            "_consulta",
            lambda _lote: [{}, {"vulns": [{"id": "GHSA-medio"}]}, {}],
        )
        monkeypatch.setattr(avisos_del_lock, "_arreglos", lambda _id, _paq: ["2.1"])

        salida = tmp_path / "informe.json"
        assert avisos_del_lock.main([str(entrada), "--salida", str(salida)]) == 0

        informe = json.loads(salida.read_text(encoding="utf-8"))
        assert [d["name"] for d in informe["dependencies"]] == ["dos"], (
            f"el aviso ha acabado en otro paquete: {informe['dependencies']}"
        )
        assert informe["dependencies"][0]["version"] == "2.0"

    def test_una_respuesta_mas_corta_no_pasa_en_silencio(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entrada = self._requirements(
            tmp_path / "req.txt", [("uno", "1.0"), ("dos", "2.0"), ("tres", "3.0")]
        )
        # Dos resultados para tres consultas: a partir del segundo, todo queda desplazado.
        monkeypatch.setattr(avisos_del_lock, "_consulta", lambda _lote: [{}, {}])

        salida = tmp_path / "informe.json"
        codigo = avisos_del_lock.main([str(entrada), "--salida", str(salida)])
        assert codigo == 1, (
            "el guion ha escrito un informe con las consultas y los resultados descuadrados. "
            "El emparejado es por posición, así que eso no es un informe con menos avisos: es "
            "un informe que dice de quién es cada aviso y se equivoca."
        )
