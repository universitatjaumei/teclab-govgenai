"""AUT.7 (#117), revisado en la PR #210: lo que la retención y los topes prometían y no cumplían.

La revisión de Copilot encontró cuatro sitios:

1. **El barrido de caducados no lo llamaba nada.** Existía y tenía test, pero ningún arranque ni
   programador lo invocaba: la descarga respondía 404 al caducar y el fichero y su fila se
   quedaban para siempre. `retencion_dias` prometía un borrado que no ocurría, y el argumento de
   esta funcionalidad es de protección de datos.
2. **Ficheros huérfanos.** Las subidas al almacenamiento no forman parte de la transacción: si
   una subida o el commit posterior fallaban, los ficheros ya escritos quedaban sin fila, y el
   barrido —que recorre filas— no los encontraría nunca.
3. **El tope de salida no cabía.** Un contrato podía declarar 100 MB de artefactos y una
   petición podía traer 64 MB de entrada, los dos en el mismo `tmpfs` de 128 MB.
4. **El modo local descartaba en silencio.** El sandbox HTTP avisa con `ARTEFACTOS_NO_DECLARADOS`
   cuando el guion escribe ficheros que la función no declara; el modo local los tiraba sin
   decir nada. Es la divergencia entre entornos que la #194 vino a quitar.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.tests.modules.redaccion.test_aut7_los_artefactos_se_guardan_y_se_sirven import (
    AlmacenDeMentira,
    _bruto,
    _una_funcion,
)


class _SesionPrestada:
    """Hace pasar la sesión del test por una fábrica de sesiones, sin cerrarla al salir."""

    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc) -> None:
        return None


class TestElBarridoCorreSolo:
    """1 — una capacidad que el arranque no llama no existe (la lección de DIN.4)."""

    @pytest.mark.asyncio
    async def test_una_pasada_borra_lo_caducado_y_lo_deja_escrito(self, db_session):
        from sqlalchemy import select

        from server.app.modules.redaccion.database.models import HubFuncionArtefacto
        from server.app.modules.redaccion.funciones_artefactos import (
            guardar_artefactos,
            una_pasada_de_caducados,
        )

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        guardados = await guardar_artefactos(
            db_session,
            [_bruto("viejo.csv", b"viejo")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )
        guardados[0].expira_en = datetime.now(timezone.utc) - timedelta(days=1)
        await db_session.commit()

        borrados = await una_pasada_de_caducados(
            lambda: _SesionPrestada(db_session), almacen=almacen
        )

        assert borrados == 1
        assert guardados[0].storage_key in almacen.borrados
        # **Y commitea**: sin el commit, la pasada diría «borrado» y la fila seguiría ahí al
        # cerrar la sesión — el defecto que DIN.7 encontró en el job de calidad.
        await db_session.rollback()
        quedan = (
            await db_session.execute(
                select(HubFuncionArtefacto).where(
                    HubFuncionArtefacto.organizacion_id == organizacion
                )
            )
        ).scalars().all()
        assert quedan == []

    @pytest.mark.asyncio
    async def test_un_fallo_de_una_pasada_no_para_el_bucle(self, monkeypatch):
        """Si la primera pasada revienta, el bucle lo registra y espera a la siguiente."""
        import asyncio

        from server.app.modules.redaccion import funciones_artefactos

        pasadas = []

        async def _pasada_que_falla(*args, **kwargs):
            pasadas.append(1)
            raise RuntimeError("el almacenamiento no responde")

        async def _sleep_que_corta(_segundos):
            raise asyncio.CancelledError

        monkeypatch.setattr(funciones_artefactos, "una_pasada_de_caducados", _pasada_que_falla)
        monkeypatch.setattr(funciones_artefactos.asyncio, "sleep", _sleep_que_corta)

        with pytest.raises(asyncio.CancelledError):
            await funciones_artefactos.bucle_de_caducados(object(), almacen=AlmacenDeMentira())

        # Llegó a dormir —o sea, el RuntimeError no salió del bucle— tras una pasada.
        assert pasadas == [1]

    def test_el_arranque_lo_pone_en_marcha(self):
        """Lo que hizo falta en DIN.4: comprobar que el arranque lo llama, no que exista."""
        import ast

        main = Path(__file__).resolve().parents[3] / "app" / "main.py"
        arbol = ast.parse(main.read_text(encoding="utf-8"))
        # `lifespan` envuelve a `_arranque` para resumir sus fallos; el arranque de verdad es
        # éste, y es donde tiene que estar.
        arranque = next(
            n
            for n in ast.walk(arbol)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_arranque"
        )
        llamadas = {
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(arranque)
            if isinstance(n, ast.Call)
        }
        assert "bucle_de_caducados" in llamadas


class _AlmacenQueFallaAlSegundo(AlmacenDeMentira):
    async def put(self, key: str, data: bytes) -> None:
        if self.contenido:
            raise OSError("el bucket no responde")
        await super().put(key, data)


class TestNoQuedanFicherosSinFila:
    """2 — lo que se subió y no llegó a tener fila se borra, porque el barrido no lo vería."""

    @pytest.mark.asyncio
    async def test_si_falla_una_subida_se_borran_las_anteriores(self, db_session):
        from server.app.modules.redaccion.funciones_artefactos import guardar_artefactos

        almacen = _AlmacenQueFallaAlSegundo()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)

        with pytest.raises(OSError):
            await guardar_artefactos(
                db_session,
                [_bruto("uno.csv", b"1"), _bruto("dos.csv", b"2")],
                almacen=almacen,
                organizacion_id=organizacion,
                funcion_id=funcion.id,
                version=1,
                retencion_dias=7,
            )

        assert almacen.contenido == {}
        assert len(almacen.borrados) == 1

    @pytest.mark.asyncio
    async def test_si_falla_lo_que_viene_despues_se_pueden_deshacer(self, db_session):
        from server.app.modules.redaccion.funciones_artefactos import (
            deshacer_artefactos,
            guardar_artefactos,
        )

        almacen = AlmacenDeMentira()
        organizacion = uuid.uuid4()
        funcion = await _una_funcion(db_session, organizacion)
        guardados = await guardar_artefactos(
            db_session,
            [_bruto("uno.csv", b"1"), _bruto("dos.csv", b"2")],
            almacen=almacen,
            organizacion_id=organizacion,
            funcion_id=funcion.id,
            version=1,
            retencion_dias=7,
        )

        await deshacer_artefactos(guardados, almacen=almacen)

        assert almacen.contenido == {}

    def test_el_router_los_deshace_si_falla_el_registro(self):
        """El commit lo hace `_anotar_en_el_registro`: si falla, los ficheros no tienen fila."""
        import ast

        router = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "routers"
            / "redaccion"
            / "funciones_run_router.py"
        )
        arbol = ast.parse(router.read_text(encoding="utf-8"))
        protegidos = [
            n
            for n in ast.walk(arbol)
            if isinstance(n, ast.Try)
            and any(
                isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_anotar_en_el_registro"
                for c in ast.walk(ast.Module(body=n.body, type_ignores=[]))
            )
        ]
        assert protegidos, "`_anotar_en_el_registro` no va dentro de un `try`"
        deshace = any(
            isinstance(c, ast.Call) and getattr(c.func, "id", "") == "deshacer_artefactos"
            for t in protegidos
            for h in t.handlers
            for c in ast.walk(ast.Module(body=h.body, type_ignores=[]))
        )
        assert deshace, "si el registro falla, el router no deshace los artefactos"


class TestElTopeDeSalidaCabe:
    """3 — entrada y salida comparten el `tmpfs` de 128 MB: los dos topes tienen que caber."""

    def _tmpfs_bytes(self) -> int:
        import re

        compose = (
            Path(__file__).resolve().parents[4] / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        casado = re.search(r"/tmp/sandbox:size=(\d+)M", compose)
        assert casado, "el sandbox ya no monta su temporal como tmpfs con tamaño"
        return int(casado.group(1)) * 1024 * 1024

    def test_entrada_y_salida_juntas_caben_en_el_tmpfs(self):
        from server.app.modules.redaccion.contracts.funciones import (
            MAXIMO_BYTES_DE_SALIDA,
        )
        from server.app.modules.redaccion.funciones_service import MAXIMO_BYTES_DE_ENTRADA

        assert MAXIMO_BYTES_DE_ENTRADA + MAXIMO_BYTES_DE_SALIDA <= self._tmpfs_bytes()

    def test_un_contrato_no_puede_declarar_mas(self):
        from pydantic import ValidationError

        from server.app.modules.redaccion.contracts.funciones import (
            MAXIMO_BYTES_DE_SALIDA,
            ArtefactosDeSalida,
        )

        with pytest.raises(ValidationError):
            ArtefactosDeSalida(
                maximo=1, maximo_bytes=MAXIMO_BYTES_DE_SALIDA + 1, retencion_dias=7
            )

    def test_y_el_sandbox_tampoco_lo_acepta(self):
        """El sandbox es otro proyecto y valida su propia petición: el tope tiene que coincidir."""
        import importlib.util
        import sys

        from server.app.modules.redaccion.contracts.funciones import MAXIMO_BYTES_DE_SALIDA

        raiz = Path(__file__).resolve().parents[4] / "services" / "script_sandbox"
        spec = importlib.util.spec_from_file_location(
            "_contratos_del_sandbox_210", raiz / "sandbox" / "contracts.py"
        )
        assert spec and spec.loader
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = modulo
        spec.loader.exec_module(modulo)

        campo = modulo.ExecuteExtractionRequest.model_fields["artefactos_maximo_bytes"]
        tope = next(m.le for m in campo.metadata if getattr(m, "le", None) is not None)
        assert tope == MAXIMO_BYTES_DE_SALIDA


class TestElModoLocalAvisaIgual:
    """4 — el modo local hace lo mismo que el sandbox HTTP, también al descartar."""

    @pytest.mark.asyncio
    async def test_lo_que_el_guion_escribe_sin_declararlo_se_avisa(self):
        from server.app.core.sandbox_client import LocalSandboxClient

        salida = await LocalSandboxClient().execute_extraction_script(
            # Con una librería y no con `open`, que el auditor deniega: es como un guion de verdad
            # produce un fichero.
            code=(
                "import pandas\n"
                "pandas.DataFrame({'a': [1]}).to_csv(output_dir + '/salida.csv', index=False)\n"
                "result = {}\n"
            ),
            file_path=None,
            raw_text=None,
            options={},
        )

        assert "ARTEFACTOS_NO_DECLARADOS" in [w.code for w in salida.warnings], salida.warnings
