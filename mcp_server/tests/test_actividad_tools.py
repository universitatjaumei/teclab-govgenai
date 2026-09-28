"""REG.4 — el MCP remoto: mismo paquete, segundo transporte, token por petición.

El servidor stdio que existe desde MCP.1 lee `GOVGENAI_PAT` del entorno porque es mono-usuario:
un proceso, una persona, un token. Un MCP **remoto** no puede funcionar así. Si el operador
plantara un token en el entorno del servicio, todos los clientes que se conectaran actuarían con
él —mismos permisos, misma organización, mismo rastro en el registro—, y la trazabilidad que el
bloque REG existe para dar se perdería justo en la superficie que más la necesita.

De ahí la decisión de este prompt: **el token es el que presenta cada petición entrante**. Y de
ahí que los tests de este fichero no se conformen con comprobar que la tool llama a su endpoint;
levantan el transporte de verdad (streamable HTTP sobre ASGI) y siguen el `Authorization` desde la
petición MCP hasta la llamada a la API.

Dos de ellos son los que importan:

- **`test_should_carry_each_client_token_to_the_api`**: dos clientes con tokens distintos, en
  vuelo a la vez contra el mismo servidor. Es el test que descarta la implementación tentadora
  —guardar el token en una variable de módulo al empezar la petición—, que funciona con un
  cliente y mezcla identidades con dos.
- **`test_should_fail_readably_without_a_token`**: sin credencial no se llama a la API. Un 500 le
  diría a quien integra que el servidor está roto, cuando lo que pasa es que le falta el PAT.

Nota del arnés: el ciclo de vida del transporte se abre con `async with` **dentro de cada test** y
no en una fixture. El gestor de sesiones del SDK usa un grupo de tareas de anyio, y una fixture
asíncrona lo cerraría desde una tarea distinta de la que lo abrió; el fallo que da entonces
—«Attempted to exit cancel scope in a different task»— no tiene nada que ver con lo que se está
probando.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import respx

API = "http://api.test"
HOST = "mcp.test"

PAT_UNO = "pat_uno_abcdef"
PAT_DOS = "pat_dos_123456"

CENTINELA = "SENTINELA_PII_123"

#: El evento minimo que la firma tipada exige. Los tests que miran cabeceras o codigos de error
#: lo mandan entero porque desde REG.7 la validacion de presencia la hace el propio cliente MCP:
#: con menos campos, la tool falla antes de llegar a la API y no se probaria lo que se cree.
EVENTO_MINIMO = {
    "ocurrido_en": "2026-09-03T10:30:00Z",
    "actor": "u-1",
    "herramienta": "claude-cowork",
    "finalidad": "Revision de un pliego",
}


# ─────────────────────────── Arnés del transporte ──────────────────────────


def _config():
    from config import HttpConfig

    return HttpConfig(api_base_url=API, allowed_hosts=(HOST,), allowed_origins=())


@asynccontextmanager
async def servidor_mcp():
    """Levanta la aplicación ASGI del MCP remoto con su ciclo de vida abierto."""
    from http_server import build_http_app

    aplicacion = build_http_app(_config())
    async with aplicacion.router.lifespan_context(aplicacion):
        yield aplicacion


def _cabeceras(pat: str | None, *, authorization: str | None = None) -> dict[str, str]:
    cabeceras = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Host": HOST,
    }
    if authorization is not None:
        cabeceras["Authorization"] = authorization
    elif pat is not None:
        cabeceras["Authorization"] = f"Bearer {pat}"
    return cabeceras


async def _llama(
    app,
    nombre: str,
    argumentos: dict,
    *,
    pat: str | None = None,
    authorization: str | None = None,
) -> dict:
    """Invoca una tool por el transporte real y devuelve el resultado JSON-RPC.

    Se habla streamable HTTP contra la aplicación ASGI en vez de llamar a la función de la tool:
    lo que este prompt cambia es de dónde sale el token, y eso sólo se ve si la petición entra por
    donde entra de verdad.
    """
    cuerpo = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": nombre, "arguments": argumentos},
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://{HOST}"
    ) as cliente:
        respuesta = await cliente.post(
            "/mcp", json=cuerpo, headers=_cabeceras(pat, authorization=authorization)
        )

    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["result"]


def _texto(resultado: dict) -> str:
    return "\n".join(bloque.get("text", "") for bloque in resultado.get("content", []))


def _payload(resultado: dict) -> dict:
    assert not resultado.get("isError"), _texto(resultado)
    return json.loads(_texto(resultado))


# ─────────────────────────── El token por petición ─────────────────────────


class TestElTokenViajaConLaPeticion:

    @respx.mock
    async def test_should_forward_the_incoming_bearer_to_the_api(self):
        ruta = respx.post(f"{API}/api/v1/actividad").mock(
            return_value=httpx.Response(
                201, json={"id": "0d3b", "registrado_en": "2026-09-03T10:30:00Z"}
            )
        )

        async with servidor_mcp() as app:
            await _llama(app, "registrar_actividad", EVENTO_MINIMO, pat=PAT_UNO)

        assert ruta.called
        assert ruta.calls.last.request.headers["authorization"] == f"Bearer {PAT_UNO}"

    @respx.mock
    async def test_should_serve_more_than_one_call_per_process(self):
        """VAS.4 — el defecto que la sesión MCP real destapó, y que ningún test veía.

        El pool de `httpx` se cerraba en el ciclo de vida de **FastMCP**, y con `stateless_http`
        ese ciclo corre **por petición**: el `aclose()` del `finally` cerraba el pool compartido
        en cuanto acababa la primera llamada, así que la segunda moría con «Cannot send a
        request, as the client has been closed». El servidor remoto servía **una sola llamada por
        proceso**.

        Y lo que hace este test necesario es que el de dos clientes concurrentes **pasaba**: sus
        dos peticiones empiezan antes de que el ciclo de la primera termine, así que las dos
        encuentran el pool abierto. Lo que fallaba era lo secuencial, que es lo normal.
        """
        ruta = respx.post(f"{API}/api/v1/anonimizacion/spans").mock(
            return_value=httpx.Response(200, json={"spans": []})
        )

        async with servidor_mcp() as app:
            primera = await _llama(app, "detectar_pii", {"text": "uno"}, pat=PAT_UNO)
            segunda = await _llama(app, "detectar_pii", {"text": "dos"}, pat=PAT_UNO)

        assert not primera.get("isError"), _texto(primera)
        assert not segunda.get("isError"), _texto(segunda)
        assert len(ruta.calls) == 2

    @respx.mock
    async def test_should_carry_each_client_token_to_the_api(self):
        """Dos clientes en vuelo a la vez contra el mismo servidor, cada uno con el suyo.

        Es el test que descarta guardar el token en una variable de módulo: con un solo cliente
        esa implementación pasa, y con dos mezcla identidades.
        """
        ruta = respx.post(f"{API}/api/v1/anonimizacion/spans").mock(
            return_value=httpx.Response(200, json={"spans": []})
        )

        async with servidor_mcp() as app:
            await asyncio.gather(
                _llama(app, "detectar_pii", {"text": "uno"}, pat=PAT_UNO),
                _llama(app, "detectar_pii", {"text": "dos"}, pat=PAT_DOS),
            )

        por_texto = {
            json.loads(llamada.request.content)["text"]: llamada.request.headers[
                "authorization"
            ]
            for llamada in ruta.calls
        }
        assert por_texto == {"uno": f"Bearer {PAT_UNO}", "dos": f"Bearer {PAT_DOS}"}

    @respx.mock
    async def test_should_fail_readably_without_a_token(self):
        """Sin credencial no se llama a la API: el problema es del cliente, no del servidor."""
        ruta = respx.post(f"{API}/api/v1/anonimizacion/spans")

        async with servidor_mcp() as app:
            resultado = await _llama(app, "detectar_pii", {"text": "hola"}, pat=None)

        assert resultado.get("isError"), resultado
        mensaje = _texto(resultado)
        assert "PAT" in mensaje, mensaje
        assert not ruta.called, (
            "llamar a la API sin token sólo sirve para que el 401 llegue disfrazado de fallo "
            "nuestro."
        )

    @respx.mock
    async def test_should_reject_an_authorization_that_is_not_a_bearer(self):
        """Un cliente mal configurado se entera aquí, y no buscando el fallo en su token."""
        ruta = respx.post(f"{API}/api/v1/anonimizacion/spans")

        async with servidor_mcp() as app:
            resultado = await _llama(
                app,
                "detectar_pii",
                {"text": "hola"},
                authorization="Basic dXNlcjpwYXNz",
            )

        assert resultado.get("isError"), resultado
        assert "Bearer" in _texto(resultado)
        assert not ruta.called


# ─────────────────────────── Las tres tools ────────────────────────────────


class TestLasTresTools:

    @respx.mock
    async def test_should_register_activity_and_return_the_receipt(self):
        respx.post(f"{API}/api/v1/actividad").mock(
            return_value=httpx.Response(
                201, json={"id": "0d3b", "registrado_en": "2026-09-03T10:30:00Z"}
            )
        )

        async with servidor_mcp() as app:
            resultado = await _llama(
                app, "registrar_actividad", EVENTO_MINIMO, pat=PAT_UNO
            )

        assert _payload(resultado)["id"] == "0d3b"

    @respx.mock
    async def test_should_detect_pii_and_return_the_spans(self):
        respx.post(f"{API}/api/v1/anonimizacion/spans").mock(
            return_value=httpx.Response(
                200,
                json={
                    "spans": [
                        {
                            "start": 4,
                            "end": 13,
                            "type": "DNI",
                            "original_text": "12345678Z",
                            "suggested_fake": "87654321X",
                        }
                    ]
                },
            )
        )

        async with servidor_mcp() as app:
            resultado = await _llama(
                app, "detectar_pii", {"text": f"DNI 12345678Z {CENTINELA}"}, pat=PAT_UNO
            )

        assert _payload(resultado)["spans"][0]["type"] == "DNI"

    @respx.mock
    async def test_should_anonymise_text_and_return_what_it_applied(self):
        respx.post(f"{API}/api/v1/anonimizacion/replace").mock(
            return_value=httpx.Response(
                200, json={"text_anonimizado": "DNI 87654321X", "spans_aplicados": []}
            )
        )

        async with servidor_mcp() as app:
            resultado = await _llama(
                app, "anonimizar_texto", {"text": "DNI 12345678Z"}, pat=PAT_UNO
            )

        assert _payload(resultado)["text_anonimizado"] == "DNI 87654321X"

    @respx.mock
    async def test_should_send_the_event_as_the_body_of_the_post(self):
        """El evento se manda tal cual: nada se rellena por su cuenta.

        Un valor por defecto puesto en el cliente MCP sería un dato del registro que no declaró
        quien lo usó.
        """
        ruta = respx.post(f"{API}/api/v1/actividad").mock(
            return_value=httpx.Response(201, json={"id": "x", "registrado_en": "z"})
        )
        evento = {
            "ocurrido_en": "2026-09-03T10:30:00Z",
            "actor": "u-1",
            "herramienta": "claude-cowork",
            "finalidad": "Revisión de un pliego",
        }

        async with servidor_mcp() as app:
            await _llama(app, "registrar_actividad", evento, pat=PAT_UNO)

        assert json.loads(ruta.calls.last.request.content) == evento

    @respx.mock
    async def test_should_leave_out_the_optional_fields_nobody_filled(self):
        """Lo que no se declara no viaja, y menos como `null`.

        `categorias_datos` no admite nulo en el contrato —su defecto es la lista vacía—, así que
        mandar `null` por rellenar el hueco sería un 422 provocado por el cliente. Y `agente:
        null` sería ruido: el registro no gana nada guardando «no dijo nada» de forma explícita.
        """
        ruta = respx.post(f"{API}/api/v1/actividad").mock(
            return_value=httpx.Response(201, json={"id": "x", "registrado_en": "z"})
        )

        async with servidor_mcp() as app:
            await _llama(
                app,
                "registrar_actividad",
                {
                    "ocurrido_en": "2026-09-03T10:30:00Z",
                    "actor": "u-1",
                    "herramienta": "copilot",
                    "finalidad": "Una consulta",
                },
                pat=PAT_UNO,
            )

        enviado = json.loads(ruta.calls.last.request.content)
        assert set(enviado) == {"ocurrido_en", "actor", "herramienta", "finalidad"}

    async def test_should_publish_the_event_contract_in_the_tool_schema(self):
        """Lo que un cliente MCP recibe de `tools/list` tiene que ser el contrato.

        Con `evento: dict` el esquema era `{"type": "object", "additionalProperties": true}`: sin
        un solo nombre de campo y, encima, prometiendo que cualquier extra vale cuando el
        servidor los rechaza con 422. Un agente lo descubría a base de 422 en bucle.
        """
        from http_server import build_http_server

        servidor = build_http_server(_config())
        registrar = next(
            t for t in await servidor.list_tools() if t.name == "registrar_actividad"
        )
        esquema = registrar.inputSchema

        assert set(esquema["properties"]) == {
            "ocurrido_en",
            "actor",
            "herramienta",
            "agente",
            "finalidad",
            "modelo_usado",
            "categorias_datos",
            "payload_hash",
            # AUT.5 — el hash del programa que corrió, que enlaza el uso con su función del
            # catálogo. Lo vigila `test_reg7_la_tool_declara_el_contrato`: un campo del
            # contrato que falte aquí no se puede mandar por MCP.
            "funcion_sha256",
        }, esquema["properties"].keys()
        assert set(esquema["required"]) == {
            "ocurrido_en",
            "actor",
            "herramienta",
            "finalidad",
        }, esquema.get("required")

    async def test_should_describe_the_rules_that_the_type_cannot_express(self):
        """«Con zona horaria» y «SHA-256» no se deducen de `str`: van en la descripción."""
        from http_server import build_http_server

        servidor = build_http_server(_config())
        registrar = next(
            t for t in await servidor.list_tools() if t.name == "registrar_actividad"
        )
        propiedades = registrar.inputSchema["properties"]

        assert "zona horaria" in propiedades["ocurrido_en"]["description"]
        assert "SHA-256" in propiedades["payload_hash"]["description"]
        # Y el puntero al catálogo, que es lo que evita que cada herramienta invente códigos.
        assert "categorias" in propiedades["categorias_datos"]["description"]

    async def test_should_expose_the_three_new_tools(self):
        from http_server import build_http_server

        servidor = build_http_server(_config())
        nombres = {tool.name for tool in await servidor.list_tools()}

        assert {"registrar_actividad", "detectar_pii", "anonimizar_texto"} <= nombres

    async def test_should_not_gate_registering_behind_a_confirmation(self):
        """`update_chatbot` pide confirmación porque muta producción in-place.

        Registrar actividad es añadir metadatos: no muta nada, y una puerta de confirmación en
        una tool que un agente va a llamar de forma rutinaria sólo conseguiría que se dejara de
        llamar — con lo que el registro quedaría vacío, que es peor que una entrada de más.
        """
        from http_server import build_http_server

        servidor = build_http_server(_config())
        registrar = next(
            tool
            for tool in await servidor.list_tools()
            if tool.name == "registrar_actividad"
        )

        assert "confirm" not in json.dumps(registrar.inputSchema).lower()


# ─────────────────────────── Los errores del servidor ──────────────────────


class TestLosErroresLleganLegibles:

    @respx.mock
    async def test_should_name_the_missing_scope_on_a_403(self):
        respx.post(f"{API}/api/v1/actividad").mock(
            return_value=httpx.Response(
                403,
                json={
                    "detail": {
                        "code": "PAT_SCOPE_MISSING",
                        "missing": ["actividad:write"],
                    }
                },
            )
        )

        async with servidor_mcp() as app:
            resultado = await _llama(
                app, "registrar_actividad", EVENTO_MINIMO, pat=PAT_UNO
            )

        assert resultado.get("isError")
        assert "actividad:write" in _texto(resultado), _texto(resultado)

    @respx.mock
    async def test_should_carry_the_body_detail_on_a_422(self):
        respx.post(f"{API}/api/v1/actividad").mock(
            return_value=httpx.Response(
                422,
                json={
                    "detail": [{"loc": ["body", "ocurrido_en"], "msg": "sin zona horaria"}]
                },
            )
        )

        async with servidor_mcp() as app:
            resultado = await _llama(
                app, "registrar_actividad", EVENTO_MINIMO, pat=PAT_UNO
            )

        assert resultado.get("isError")
        assert "ocurrido_en" in _texto(resultado), _texto(resultado)

    @respx.mock
    async def test_should_say_the_token_is_rejected_on_a_401(self):
        respx.post(f"{API}/api/v1/anonimizacion/spans").mock(
            return_value=httpx.Response(401, json={"detail": "token revocado"})
        )

        async with servidor_mcp() as app:
            resultado = await _llama(app, "detectar_pii", {"text": "x"}, pat=PAT_UNO)

        assert resultado.get("isError")
        assert "401" in _texto(resultado)


# ─────────────────────────── El stdio no cambia ────────────────────────────


class TestElStdioSigueComoEstaba:

    def test_should_still_require_the_environment_pat(self):
        """Es mono-usuario: un proceso, una persona, un token. Ahí el entorno vale."""
        from config import ConfigError, load_config

        with pytest.raises(ConfigError) as excinfo:
            load_config({"GOVGENAI_API_BASE_URL": API})

        assert "GOVGENAI_PAT" in str(excinfo.value)

    def test_should_not_ask_the_http_server_for_an_environment_pat(self):
        """Y aquí lo contrario, que es el punto entero del prompt.

        Un PAT en el entorno de un servicio multi-cliente haría que todos los que se conectaran
        actuaran con el mismo: mismos permisos, misma organización y mismo rastro en el registro.
        """
        from config import load_http_config

        cfg = load_http_config(
            {"GOVGENAI_API_BASE_URL": API, "GOVGENAI_MCP_ALLOWED_HOSTS": HOST}
        )

        assert cfg.api_base_url == API
        assert not hasattr(cfg, "pat")

    def test_should_demand_the_allowed_hosts(self):
        """Sin ellos el transporte responde 421 a todo, y el fallo no se parece a su causa.

        La protección contra DNS rebinding del SDK valida el `Host`, y detrás del proxy inverso
        el `Host` es el del dominio institucional, no `localhost`. Que falte se dice al arrancar.
        """
        from config import ConfigError, load_http_config

        with pytest.raises(ConfigError) as excinfo:
            load_http_config({"GOVGENAI_API_BASE_URL": API})

        assert "GOVGENAI_MCP_ALLOWED_HOSTS" in str(excinfo.value)


class TestLaFronteraDelPaquete:

    def test_should_not_import_anything_from_the_server_application(self):
        """MCP.1 lo dejó dicho: este paquete es un cliente HTTP más, como el frontend.

        Si importara la aplicación del servidor, el MCP remoto pasaría a necesitar su venv y su
        base de datos, y dejaría de poder desplegarse como el proceso pequeño que es.

        Se busca `server.app` en sentencias de importación, no la cadena a secas: un fichero
        puede explicar la regla —como éste— sin infringirla, y `from server import build_server`
        es legítimo porque ahí `server` es el módulo stdio de este mismo paquete.
        """
        importa = re.compile(r"^\s*(?:from|import)\s+server\.app\b", re.MULTILINE)
        raiz = Path(__file__).resolve().parent.parent

        ofensores = [
            fichero.name
            for fichero in raiz.rglob("*.py")
            if ".venv" not in fichero.parts
            and importa.search(fichero.read_text(encoding="utf-8"))
        ]

        assert ofensores == []
