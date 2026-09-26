"""Issue #159, parte 1 de 3 — tiempo máximo de consulta.

**La mitad que la #149 no cerró.** Los techos de memoria contienen el daño: una operación
desbocada mata su contenedor en vez de dejar la VM sin responder. Pero **nada impide que la
operación se desboque**, y el 2026-09-24 pasó dos veces en la misma tarde. La primera dejó el
sitio 50 minutos sin atender nada, y no la causó ningún usuario: fue una consulta interna.

**Por qué esta parte va primera.** Es configuración de la conexión, así que cubre **toda**
consulta del sistema, incluidas las que nadie ha escrito todavía. Ninguna de las otras dos
—recorridos acotados y límite de concurrencia— protege lo que aún no existe.

**Lo que hace y lo que no.** `statement_timeout` corta la consulta en el servidor de base de
datos y libera la conexión. No evita que alguien escriba una consulta cara; evita que una
consulta cara se quede la conexión para siempre, que es distinto y es lo que ocurrió: la
aplicación seguía viva y sin poder atender nada.

**Se prueba contra PostgreSQL de verdad**, con `pg_sleep`, porque un test que comprobara que la
opción está escrita en el sitio correcto no demostraría que el servidor la aplica — y lo que hay
que saber es lo segundo. Es el mismo criterio con el que la #161 se probó por el camino real y no
por el de los dobles.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from server.app.database.db import opciones_de_conexion
from server.app.modules.agents_hub.database.connection import create_async_engine


class TestElServidorCortaLaConsultaLarga:

    async def test_una_consulta_que_se_pasa_del_tiempo_se_corta(self, db_url: str) -> None:
        """La prueba de saturación que la issue pedía: qué pasa cuando algo pide de más.

        Sin esto, `pg_sleep(5)` con un límite de medio segundo se quedaría los cinco segundos, y
        una consulta de verdad se quedaría los que hiciera falta — que el 2026-09-24 fueron
        cincuenta minutos.
        """
        motor = create_async_engine(db_url, statement_timeout_ms=500)
        try:
            async with motor.connect() as conexion:
                with pytest.raises(Exception) as exc:
                    await conexion.execute(text("SELECT pg_sleep(5)"))
            # Postgres cancela por tiempo con `QueryCanceled` (SQLSTATE 57014). Se comprueba el
            # motivo y no sólo que haya fallado: un fallo de conexión también levantaría, y daría
            # este test por bueno sin que el límite existiera.
            assert "57014" in str(exc.value) or "canc" in str(exc.value).lower(), (
                f"la consulta falló por otra cosa: {exc.value}"
            )
        finally:
            await motor.dispose()

    async def test_una_consulta_normal_no_se_ve_afectada(self, db_url: str) -> None:
        """El límite no puede estar cortando trabajo legítimo, que es la forma de que alguien lo
        quite entero."""
        motor = create_async_engine(db_url, statement_timeout_ms=5000)
        try:
            async with motor.connect() as conexion:
                resultado = await conexion.execute(text("SELECT 1"))
                assert resultado.scalar() == 1
        finally:
            await motor.dispose()


class TestLaOpcionSeAplicaEnTodasPartes:
    """Hay **dos** fábricas de engine, y un arreglo en una sola no cubre la otra.

    `database/db.py` monta el de la plataforma y `agents_hub/database/connection.py` el del hub.
    Ya divergieron una vez por el DSN de reserva —dos copias del mismo valor, y la que no se toca
    sigue conectando a la base vieja—, y se resolvió unificándolo en `_dsn()`. El tiempo máximo
    va por el mismo camino y por la misma razón.
    """

    def test_el_dsn_de_postgres_lleva_el_tiempo_maximo(self) -> None:
        opciones = opciones_de_conexion("postgresql+asyncpg://u:p@h/d", 30000)

        assert opciones["server_settings"]["statement_timeout"] == "30000"

    def test_un_dsn_que_no_es_postgres_no_recibe_opciones_de_postgres(self) -> None:
        """`server_settings` es de asyncpg. Pasárselo a otro driver rompe la conexión, y el
        arreglo de una operación costosa no puede dejar el proyecto sin arrancar en otro motor:
        el codebase tiene que servir a otro despliegue cambiando variables de entorno."""
        assert opciones_de_conexion("sqlite+aiosqlite:///x.db", 30000) == {}

    def test_sin_tiempo_maximo_no_se_impone_ninguno(self) -> None:
        """Cero significa «sin límite», y es la salida para quien necesite una consulta larga de
        verdad —una migración de datos, un barrido— sin tener que quitar la protección del todo."""
        assert opciones_de_conexion("postgresql+asyncpg://u:p@h/d", 0) == {}

    def test_las_dos_fabricas_lo_aplican(self) -> None:
        """El guardarraíl del cableado: que la función exista no sirve si alguien no la llama.

        Es el mismo defecto que la revisión de la PR #168 encontró dos veces en un día —un helper
        escrito y no usado, y un transporte que no estaba enchufado—, así que aquí se comprueba
        el uso y no la existencia.
        """
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[2] / "app"
        for ruta in (
            raiz / "database" / "db.py",
            raiz / "modules" / "agents_hub" / "database" / "connection.py",
        ):
            texto = ruta.read_text(encoding="utf-8")
            assert "opciones_de_conexion" in texto, (
                f"{ruta.name} crea un engine sin aplicar el tiempo máximo de consulta. Las dos "
                f"fábricas tienen que pasar por la misma función o volverán a divergir."
            )
