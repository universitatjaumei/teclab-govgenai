"""SEC.9.6 — Controles que estaban declarados y no se aplicaban, y guardas a medias.

Los cinco hallazgos medios de la auditoría del 2026-08-24. Tienen en común algo que conviene
nombrar: **no son controles ausentes, son controles presentes que no llegan a ejecutarse**. Un
límite que nadie pasa, una cuota cuyo parámetro nunca se rellena, un gate que se salta con una
variable de entorno, un `workspace_id` que no se usa. Es peor que la ausencia, porque el código
lee como si estuviera cubierto.

- **NUEVO-5**: `POST /redaccion/llm-drafts/sample` hacía `file.read()` sin límite. Es el único
  `UploadFile` que quedó fuera de SEC.6 y SEC.8.2.
- **NUEVO-6**: `anon_ip_daily_token_quota` existe en `core/quotas.py` y **nunca se evalúa**,
  porque su único llamador no pasa `ip=`. Y el actor del widget es `widget:{chatbot_id}`, así que
  todos los visitantes anónimos de un asistente comparten un cubo de peticiones: uno solo deja el
  widget público sin servicio para los demás.
- **NUEVO-7**: el gate que prohíbe el sandbox local en producción se salta con `TESTING=1`, y el
  `subprocess` del sandbox local heredaba `os.environ` entero —`JWT_SECRET_KEY`, `DATABASE_URL`,
  `AUTOMATIA_SIGNING_KEY`— porque no se le pasaba `env=`.
- **NUEVO-8**: `hub_agents_router` ignora el `workspace_id` de la ruta y devuelve *una
  interacción cualquiera* del usuario; y `workspaces_router` es el único router de `redaccion/`
  sin `require_module("informes")`.
- **NUEVO-8b**: `hub_organizaciones_router` aceptaba `partner_id` del cuerpo sin comprobarlo.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path



class TestLaSubidaSinLimite:
    """NUEVO-5. Se comprueba sobre el código y no con un fichero gigante: fabricar el límite
    real en un test lo haría lento y frágil, y lo que falló aquí fue **no llamar a la guarda**."""

    def test_should_not_read_an_upload_without_a_limit(self):
        texto = Path("app/routers/redaccion/llm_drafts_router.py").read_text(encoding="utf-8")
        assert "read_within_limit" in texto, (
            "describe_sample_file hace file.read() sin límite: es el único UploadFile fuera de "
            "SEC.6/SEC.8.2, y agota la memoria del proceso con un fichero grande"
        )
        assert "await file.read()" not in texto


class TestLaCuotaDelAnonimoSeAplica:
    """NUEVO-6. El parámetro existía y nadie lo rellenaba."""

    def test_should_pass_the_ip_to_the_quota_check(self):
        texto = Path("app/api/v1/hub_chat.py").read_text(encoding="utf-8")
        assert re.search(r"assert_within_quota\([^)]*ip=", texto, re.S), (
            "assert_within_quota se llama sin ip=, así que anon_ip_daily_token_quota "
            "(quotas.py) es código muerto y el tráfico anónimo del widget no tiene cuota"
        )
        assert re.search(r"contabilizar_interaccion\([^)]*ip=", texto, re.S), (
            "contabilizar_interaccion sin ip=: lo gastado por el anónimo no se acumula en "
            "ningún contador que su cuota pueda mirar"
        )

    def test_should_rate_limit_the_anonymous_visitor_by_ip(self):
        """El cubo por chatbot no basta: con el actor `widget:{chatbot_id}`, un visitante
        agota el cupo de todos los demás visitantes de ese asistente."""
        texto = Path("app/api/v1/hub_chat.py").read_text(encoding="utf-8")
        # `limitar_chat` ya cae a la IP cuando no hay actor (`rate_limit.py`), así que el
        # arreglo es no darle el actor compartido del widget. Se comprueba esa forma exacta
        # porque es la decisión: el anónimo no tiene identidad que limitar, tiene origen.
        assert re.search(r"actor_id=None if es_widget", texto), (
            "el límite de peticiones del widget se aplica sobre el actor compartido "
            "widget:{chatbot_id}, así que un visitante agota el cupo de todos los demás"
        )


class TestElGateDelSandbox:
    """NUEVO-7."""

    def test_should_not_let_testing_bypass_the_production_gate(self):
        from server.app.core.config import _assert_configuracion_de_produccion

        fuente = inspect.getsource(_assert_configuracion_de_produccion)
        assert "TESTING" in fuente, (
            "el gate sólo mira sandbox_mode=='local'. Con ENVIRONMENT=production, "
            "SANDBOX_MODE=http y TESTING=1 el servidor arranca sin protestar y ejecuta los "
            "scripts en el host, que es justo lo que el gate dice evitar"
        )

    def test_should_not_leak_the_process_environment_to_the_sandbox(self):
        texto = Path("app/core/sandbox_client.py").read_text(encoding="utf-8")
        assert "env=" in texto, (
            "subprocess.Popen sin env=: el proceso del sandbox local hereda os.environ "
            "entero, con JWT_SECRET_KEY, DATABASE_URL y AUTOMATIA_SIGNING_KEY dentro"
        )


class TestGuardasAMedias:
    """NUEVO-8."""

    def test_should_use_the_requested_workspace(self):
        texto = Path("app/routers/hub_agents_router.py").read_text(encoding="utf-8")
        # La consulta tiene que filtrar por el id de la ruta, no sólo por el usuario. Se busca
        # el filtro y no la palabra `workspace_id`, que ya aparecía en el mensaje del 404.
        assert "HubInteraction.id ==" in texto, (
            "export_agent_workspace ignora el workspace_id de la ruta: hace "
            "select(HubInteraction).where(user_id == ...).limit(1), o sea exporta una "
            "interacción cualquiera y la presenta como el workspace pedido"
        )

    def test_should_require_the_reports_module_on_every_redaccion_router(self):
        """Todo router de `redaccion/` exige un módulo: `informes` o, desde el 2026-10-05, el
        catálogo de funciones, que pasó a `automatizacion` (ver `test_aut14_modulo_automatizacion`)."""
        base = Path("app/routers/redaccion")
        faltan = [
            ruta.name
            for ruta in sorted(base.glob("*.py"))
            if ruta.name != "__init__.py"
            and "APIRouter(" in ruta.read_text(encoding="utf-8")
            and 'require_module("informes")' not in ruta.read_text(encoding="utf-8")
            and 'require_module("automatizacion")' not in ruta.read_text(encoding="utf-8")
        ]
        assert faltan == [], (
            f"routers de redaccion/ sin require_module('informes') ni ('automatizacion'): {faltan}. "
            "Saltarse la frontera de módulos de INF.7 deja la pantalla accesible a quien no tiene el módulo"
        )

    def test_should_not_take_the_partner_from_the_body(self):
        """`partner_id` no es descriptivo: **decide quién verá la organización**.

        `_orgs_del_admin` resuelve el claim `organizacion_ids` con
        `WHERE partner_id == <su partner>`, así que aceptarlo del cuerpo dejaba a un
        administrador plantar una organización dentro del ámbito de otro. Y no hace falta
        inventar nada para arreglarlo: el partner de un administrador **es** su `user_id`, tal y
        como lo emite `login_admin`. El superadministrador sí puede decirlo (flujo de MT.13).
        """
        texto = Path("app/routers/hub_organizaciones_router.py").read_text(encoding="utf-8")
        cuerpo = texto.split("async def create_organizacion", 1)[1][:1600]
        assert "body.partner_id if user.is_superadmin else user.user_id" in cuerpo, (
            "create_organizacion toma partner_id del cuerpo sin derivarlo del actor: un "
            "administrador adscribe la organización nueva al ámbito de otro, y a partir del "
            "siguiente inicio de sesión le aparece al otro como suya"
        )


class TestElComposeDeProduccion:
    """NUEVO-9. Un fichero de producción no lleva ni un `:-` en un secreto."""

    def test_should_not_default_any_secret(self):
        ruta = Path("../docker-compose.prod.yml")
        texto = ruta.read_text(encoding="utf-8")
        sospechosas = [
            linea.strip()
            for linea in texto.splitlines()
            if re.search(r"(PASSWORD|SECRET|KEY|TOKEN)[^:]*:\s*\$\{[^}]*:-", linea)
        ]
        assert sospechosas == [], (
            "secretos con valor por omisión en el compose de producción: "
            f"{sospechosas}. Con un .env incompleto, esto levanta producción con "
            "credenciales publicadas en el repositorio."
        )
