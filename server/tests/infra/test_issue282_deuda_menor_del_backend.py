"""#282 — deuda menor del backend, cada punto con la comprobación que impide que vuelva.

Ninguno rompía nada visible, y por eso hace falta un test: un `print` de depuración que vacía el
resultado de un guion, un trabajo de calidad que se registraba dos veces, un arranque que
esperaba a la red, consultas una a una en los trabajos de fondo y columnas cuya nulabilidad se
deducía de la anotación.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
APP = RAIZ / "server" / "app"


def _wrapper_del_sandbox():
    ruta = RAIZ / "services" / "script_sandbox" / "sandbox" / "wrappers.py"
    spec = importlib.util.spec_from_file_location("_wrappers_282", ruta)
    assert spec
    assert spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.build_extraction_wrapper


def _wrapper_local():
    from server.app.core.sandbox_client import _build_local_extraction_wrapper

    return _build_local_extraction_wrapper


_GUION_QUE_DEPURA = "print('depurando')\nresult = {'metrics': [{'name': 'x', 'value': 1}]}\n"


class TestUnPrintNoVaciaElResultado:
    """Un `print` en el guion iba al mismo stdout que el JSON, y el JSON dejaba de leerse: el
    resultado salía `{}` sin aviso. Ahora lo del guion va a stderr y stdout es del resultado."""

    @pytest.mark.parametrize("construir", [_wrapper_del_sandbox, _wrapper_local], ids=["sandbox", "local"])
    def test_should_keep_the_result_when_the_script_prints(self, construir, tmp_path):
        codigo = construir()(_GUION_QUE_DEPURA, "", "", {}, str(tmp_path))
        guion = tmp_path / "guion.py"
        guion.write_text(codigo, encoding="utf-8")

        salida = subprocess.run(
            [sys.executable, str(guion)], capture_output=True, text=True, timeout=60, check=False
        )

        assert salida.returncode == 0, salida.stderr
        assert json.loads(salida.stdout) == {"metrics": [{"name": "x", "value": 1}]}
        assert "depurando" in salida.stderr

    @pytest.mark.parametrize("construir", [_wrapper_del_sandbox, _wrapper_local], ids=["sandbox", "local"])
    def test_should_not_hand_sys_to_the_script(self, construir, tmp_path):
        """El auditor prohíbe `sys` en el guion; el envoltorio no se lo puede dejar a mano."""
        codigo = construir()("result = {'tiene_sys': '_sys' in globals()}\n", "", "", {}, str(tmp_path))
        guion = tmp_path / "guion.py"
        guion.write_text(codigo, encoding="utf-8")

        salida = subprocess.run([sys.executable, str(guion)], capture_output=True, text=True, timeout=60, check=False)

        assert json.loads(salida.stdout) == {"tiene_sys": False}


@pytest.mark.asyncio
async def test_should_say_so_when_the_output_cannot_be_read():
    """Si aun así el stdout no es JSON, se dice: antes se devolvía `{}` como si nada."""
    from server.app.core.sandbox_client import _resultado_local

    resultado = _resultado_local({"returncode": 0, "stdout": "no es json", "stderr": ""}, "p")

    assert [a.code for a in resultado.warnings] == ["SCRIPT_OUTPUT_UNREADABLE"]


@pytest.mark.asyncio
async def test_should_say_the_same_from_the_http_client():
    """Revisión de la PR #313: el cliente HTTP no conocía el 500 nuevo y lo daba como
    `SCRIPT_EXECUTION_ERROR` con el JSON en crudo. Los dos clientes dicen lo mismo."""
    import httpx
    import respx

    from server.app.core.sandbox_client import HttpSandboxClient, _resultado_local

    base = "http://script-sandbox:5000"
    with respx.mock:
        respx.post(f"{base}/execute-extraction").mock(
            return_value=httpx.Response(
                500, json={"code": "SCRIPT_OUTPUT_UNREADABLE", "stdout_truncated": "{\"a\": "}
            )
        )
        http = await HttpSandboxClient(base_url=base, max_retries=0).execute_extraction_script(
            code="result = {}", file_path=None, raw_text=None, options={}
        )
    local = _resultado_local({"returncode": 0, "stdout": "{\"a\": ", "stderr": ""}, "p")

    assert [(a.code, a.message) for a in http.warnings] == [
        (a.code, a.message) for a in local.warnings
    ]


def test_should_keep_the_end_of_the_error_where_the_traceback_is():
    """Revisión de la PR #313: con los `print` del guion en stderr, quedarse con su principio
    enseñaba los `print` y cortaba el traceback, que va al final."""
    from server.app.core.sandbox_client import _resultado_local

    stderr = "depurando\n" * 200 + "KeyError: 'falta'"
    resultado = _resultado_local({"returncode": 1, "stdout": "", "stderr": stderr}, "p")

    assert resultado.warnings[0].message.endswith("KeyError: 'falta'")


class TestUnSoloTrabajoDeCalidad:
    """Dos `_quality_job` globales idénticos, uno por router, y dos registros en el arranque."""

    def test_should_be_the_same_provider_for_both_routers(self):
        from server.app.routers import hub_content_quality_router, hub_sites_router

        assert hub_sites_router.get_quality_job is hub_content_quality_router.get_quality_job

    def test_should_read_the_job_the_startup_left_in_the_app_state(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from server.app.api.deps import get_quality_job

        app = FastAPI()
        app.state.quality_job = "el trabajo"

        @app.get("/job")
        def _job(job=Depends(get_quality_job)):
            return {"job": job}

        assert TestClient(app).get("/job").json() == {"job": "el trabajo"}

    def test_should_not_keep_it_in_a_module_global(self):
        for router in ("hub_sites_router.py", "hub_content_quality_router.py"):
            texto = (APP / "routers" / router).read_text(encoding="utf-8")
            assert "global _quality_job" not in texto, router


def test_should_not_wait_for_the_network_to_start():
    """El refresco de modelos y precios de OpenRouter va en segundo plano, no antes de servir."""
    from server.app import main

    arranque = ast.parse(inspect.getsource(main._arranque).lstrip()).body[0]
    esperados = []
    pendientes = list(arranque.body)
    while pendientes:
        nodo = pendientes.pop()
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue  # lo que corre dentro de una tarea, no en el camino del arranque
        if isinstance(nodo, ast.Await):
            esperados.append(ast.unparse(nodo.value))
        pendientes.extend(ast.iter_child_nodes(nodo))
    assert "refresh_model_cache()" not in esperados
    assert "update_prices_from_openrouter()" not in esperados


def _gets_dentro_de_bucles(ruta: Path) -> list[int]:
    lineas = []
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if isinstance(nodo, (ast.For, ast.AsyncFor)):
            for hijo in ast.walk(nodo):
                if (
                    isinstance(hijo, ast.Call)
                    and isinstance(hijo.func, ast.Attribute)
                    and hijo.func.attr == "get"
                    and ast.unparse(hijo.func.value) in {"session", "self._session"}
                ):
                    lineas.append(hijo.lineno)
    return sorted(set(lineas))


def test_should_load_the_pages_of_a_quality_pass_in_one_query():
    """Una consulta por página en los trabajos de fondo: se cargan todas con un `IN`."""
    ruta = APP / "modules" / "curation" / "quality_job.py"
    assert _gets_dentro_de_bucles(ruta) == [], "hay `session.get` dentro de un bucle"


def test_should_not_query_the_documents_page_by_page():
    """Revisión de la PR #313: el mismo bucle seguía pidiendo los documentos de cada página."""
    texto = (APP / "modules" / "curation" / "quality_job.py").read_text(encoding="utf-8")
    assert "HubDocument.crawled_page_id == " not in texto


class _SesionQueCuentaParametros:
    def __init__(self):
        self.lotes: list[int] = []

    async def execute(self, stmt):
        self.lotes.append(len(stmt.whereclause.right.value))

        class _R:
            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return []

        return _R()


@pytest.mark.asyncio
async def test_should_split_a_huge_in_into_batches():
    """Revisión de la PR #313: asyncpg no admite más de 32.767 parámetros por consulta, y el
    primer rastreo de un portal grande puede traer más páginas nuevas que eso."""
    import uuid

    from server.app.modules.curation.quality_job import _paginas_por_id

    sesion = _SesionQueCuentaParametros()
    await _paginas_por_id(sesion, [uuid.uuid4() for _ in range(40_000)])

    assert sum(sesion.lotes) == 40_000
    assert max(sesion.lotes) < 32_767


def test_should_declare_nullable_on_every_column():
    """`AGENTS.md` lo exige: `Mapped[datetime]` sin `nullable=` es NOT NULL por deducción, y así
    nacieron tres columnas divergentes entre el modelo y su migración (BD.2)."""
    sin = []
    for fichero in sorted(APP.rglob("*.py")):
        for nodo in ast.walk(ast.parse(fichero.read_text(encoding="utf-8"))):
            if not (isinstance(nodo, ast.AnnAssign) and isinstance(nodo.value, ast.Call)):
                continue
            llamada = nodo.value
            if getattr(llamada.func, "id", getattr(llamada.func, "attr", "")) != "mapped_column":
                continue
            claves = {k.arg: k.value for k in llamada.keywords}
            clave_primaria = claves.get("primary_key")
            if isinstance(clave_primaria, ast.Constant) and clave_primaria.value:
                continue
            if "nullable" not in claves:
                sin.append(f"{fichero.relative_to(APP).as_posix()}:{nodo.lineno}")
    assert sin == [], f"columnas sin `nullable=` explícito: {sin}"


# ── Migraciones: en adelante, datos y esquema por separado, y repetibles ─────────────────────
#
# La auditoría contó 21 `op.execute` sin `IF NOT EXISTS` ni `ON CONFLICT` y 14 migraciones que
# mezclan esquema y datos. Las que ya existen están aplicadas en producción y reescribirlas no
# cambia nada; lo que se fija es la regla para las nuevas: una migración que falla a medias y se
# reintenta tiene que poder repetirse, y separar datos de esquema permite revertir uno sin el
# otro. Se aplica a lo que cuelgue de la cabeza que había al cerrar #282.

_FRONTERA = "1dd4d0eac847"
_VERSIONES = RAIZ / "server" / "migrations" / "versions"
_ESQUEMA = re.compile(
    r"op\.(create_table|drop_table|add_column|drop_column|alter_column|create_index|drop_index"
    r"|create_foreign_key|create_unique_constraint|create_check_constraint|drop_constraint)\("
)
_SENTENCIA = re.compile(r"op\.execute\(\s*(?:sa\.text\()?\s*(?:[rf]?\"\"\"|[rf]?['\"])(.*?)(?:\"\"\"|['\"])", re.S)


def _problemas_de_migracion(texto: str) -> list[str]:
    problemas = []
    sentencias = [m.group(1) for m in _SENTENCIA.finditer(texto)]
    datos = "op.bulk_insert(" in texto or any(
        re.match(r"\s*(INSERT|UPDATE|DELETE)\b", s, re.I) for s in sentencias
    )
    if datos and _ESQUEMA.search(texto):
        problemas.append("mezcla esquema y datos")
    for s in sentencias:
        if re.match(r"\s*(CREATE|DROP)\b", s, re.I) and not re.search(r"IF (NOT )?EXISTS", s, re.I):
            problemas.append(f"sin IF [NOT] EXISTS: {s.strip()[:60]}")
        if re.match(r"\s*INSERT\b", s, re.I) and not re.search(r"ON CONFLICT", s, re.I):
            problemas.append(f"INSERT sin ON CONFLICT: {s.strip()[:60]}")
    return problemas


def _posteriores_a_la_frontera() -> list[Path]:
    padre: dict[str, tuple[str | None, Path]] = {}
    for fichero in _VERSIONES.glob("*.py"):
        texto = fichero.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*(?::[^=]+)?=\s*['\"](\w+)['\"]", texto, re.M)
        baja = re.search(r"^down_revision\s*(?::[^=]+)?=\s*['\"](\w+)['\"]", texto, re.M)
        if rev:
            padre[rev.group(1)] = (baja.group(1) if baja else None, fichero)
    assert _FRONTERA in padre, "la frontera ya no está en la cadena: este test miraría al vacío"
    posteriores = []
    for rev, (_, fichero) in padre.items():
        actual = rev
        while actual in padre and actual != _FRONTERA:
            actual = padre[actual][0]
        if actual == _FRONTERA and rev != _FRONTERA:
            posteriores.append(fichero)
    return posteriores


def test_should_recognise_a_migration_that_breaks_the_rule():
    """El detector, contra los dos casos que tiene que cazar y uno que no."""
    mala = 'op.add_column("t", sa.Column("c"))\nop.execute("UPDATE t SET c = 1")\nop.execute("CREATE INDEX i ON t (c)")'
    buena = 'op.execute("CREATE INDEX IF NOT EXISTS i ON t (c)")'
    assert _problemas_de_migracion(mala) == [
        "mezcla esquema y datos",
        "sin IF [NOT] EXISTS: CREATE INDEX i ON t (c)",
    ]
    assert _problemas_de_migracion(buena) == []


def test_should_keep_new_migrations_repeatable_and_separate():
    malas = {
        f.name: p for f in _posteriores_a_la_frontera() if (p := _problemas_de_migracion(f.read_text(encoding="utf-8")))
    }
    assert malas == {}, (
        f"migraciones nuevas que no se pueden repetir o que mezclan esquema y datos: {malas}. "
        "Los datos, en una migración aparte; y cada `op.execute`, idempotente."
    )
