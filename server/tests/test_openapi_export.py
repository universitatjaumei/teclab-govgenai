"""
CF.1.1 (RED) — Test: el backend puede exportar openapi.json offline.

Estado inicial esperado:
  - TestOpenAPIFileExists: todos FALLAN porque los archivos no existen aún.
  - TestOpenAPIInMemory: deben PASAR si la app importa correctamente sin BD.
    Si fallan, revisar los comentarios de obstáculos conocidos.

Una vez ejecutado export_openapi.py (CF.1.2), toda la suite debe pasar.
Referencia: Plan_Contrato_OpenAPI.md, Bloque CF.1.
"""

import json
import os
from pathlib import Path

import pytest

# Variables de entorno mínimas establecidas ANTES de importar app.main,
# por si get_settings() se llama en algún import de nivel de módulo.
# Obstáculos conocidos documentados en CF.1.1:
#   - JWT_SECRET_KEY: RuntimeError si no está al instanciar Settings.
#   - DATABASE_URL: tiene default en db.py, no debería bloquear.
#   - DATABASE_URL_SYNC: usado por Alembic, puede ser necesario.
os.environ.setdefault("JWT_SECRET_KEY", "test-openapi-export-ci-key-min-32-chars!!")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://x:x@localhost/x")

# El conftest añade AI_agents_hub/ a sys.path → el prefijo correcto es server.app.*
from server.app.main import app

# server/tests/test_openapi_export.py → parents[1] = server/
_SERVER_ROOT = Path(__file__).parents[1]
OPENAPI_PATH = _SERVER_ROOT / "openapi.json"
FRONTEND_OPENAPI_PATH = _SERVER_ROOT.parent / "frontend" / "openapi.json"


class TestOpenAPIFileExists:
    """openapi.json debe existir en disco tras ejecutar export_openapi.py.

    Todos estos tests FALLAN hasta que se complete CF.1.2.
    """

    def test_server_openapi_json_exists(self):
        """server/openapi.json debe existir tras ejecutar export_openapi.py."""
        assert OPENAPI_PATH.exists(), (
            f"openapi.json no encontrado en {OPENAPI_PATH}.\n"
            "Solución: cd server && python export_openapi.py"
        )

    def test_server_openapi_json_is_valid(self):
        """server/openapi.json debe ser JSON válido y OpenAPI 3.x."""
        if not OPENAPI_PATH.exists():
            pytest.skip("Archivo no existe — ejecuta CF.1.2 primero")
        schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        assert isinstance(schema, dict), "openapi.json no es un objeto JSON"
        assert schema.get("openapi", "").startswith("3."), "No es OpenAPI 3.x"

    def test_frontend_openapi_json_exists(self):
        """frontend/openapi.json debe existir (copia de server/openapi.json)."""
        assert FRONTEND_OPENAPI_PATH.exists(), (
            f"frontend/openapi.json no encontrado en {FRONTEND_OPENAPI_PATH}.\n"
            "Solución: copiar server/openapi.json a frontend/openapi.json"
        )


class TestOpenAPIInMemory:
    """app.openapi() debe funcionar en memoria sin conexión a base de datos.

    Si estos tests fallan, el mensaje de error documenta el obstáculo.
    Crear un issue antes de continuar con CF.1.2.
    """

    def test_app_generates_openapi_schema(self):
        """app.openapi() devuelve un dict con estructura OpenAPI 3.x válida."""
        schema = app.openapi()

        assert isinstance(schema, dict), "app.openapi() no devuelve un dict"
        assert "openapi" in schema, "Falta clave raíz 'openapi'"
        assert "info" in schema, "Falta clave raíz 'info'"
        assert "paths" in schema, "Falta clave raíz 'paths'"
        assert "components" in schema, "Falta clave raíz 'components'"
        assert schema["openapi"].startswith("3."), "Versión OpenAPI no es 3.x"

    def test_schema_has_api_paths(self):
        """El schema debe contener al menos un path de la API del hub."""
        schema = app.openapi()
        paths = schema.get("paths", {})

        assert len(paths) > 0, "No hay ningún path registrado en la app"

        hub_paths = [p for p in paths if "/hub/" in p or "/api/v1/" in p]
        assert len(hub_paths) > 0, (
            "No se encontraron paths bajo /hub/ ni /api/v1/.\n"
            f"Paths registrados: {sorted(paths.keys())[:15]}"
        )

    def test_schema_has_chatbot_schemas(self):
        """components.schemas debe incluir al menos un schema de la entidad Chatbot."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})

        chatbot_schemas = [k for k in schemas if "chatbot" in k.lower()]
        assert len(chatbot_schemas) > 0, (
            "No se encontraron schemas de Chatbot en components.schemas.\n"
            "Schemas disponibles:\n  " + "\n  ".join(sorted(schemas.keys()))
        )

    def test_schema_has_client_schemas(self):
        """components.schemas debe incluir al menos un schema de la entidad Client."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})

        client_schemas = [k for k in schemas if "client" in k.lower()]
        assert len(client_schemas) > 0, (
            "No se encontraron schemas de Client en components.schemas.\n"
            "Schemas disponibles:\n  " + "\n  ".join(sorted(schemas.keys()))
        )

    def test_schema_has_llmconfig_schemas(self):
        """components.schemas debe incluir al menos un schema de LLMConfig."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})

        llm_schemas = [k for k in schemas if "llm" in k.lower() or "model" in k.lower()]
        assert len(llm_schemas) > 0, (
            "No se encontraron schemas de LLMConfig en components.schemas.\n"
            "Schemas disponibles:\n  " + "\n  ".join(sorted(schemas.keys()))
        )


class TestOpenAPISchemaContract:
    """CF.1.3 (RED) — El contrato tiene nombres de schema estables y enums correctos.

    Estos tests fallan hasta que CF.1.4 renombre los modelos Pydantic de respuesta.
    Documenta los gaps entre el contrato actual y lo que el frontend necesita.
    """

    # -- Nombres estables de Read schemas --

    def test_chatbot_read_schema_has_stable_name(self):
        """El schema de respuesta de Chatbot debe llamarse 'ChatbotRead', no usar prefijo de módulo.

        Nombre actual: server__app__routers__hub_chatbots_router__ChatbotOut
        Nombre esperado: ChatbotRead
        Impacto: Orval genera tipos TypeScript con el nombre del schema.
        Un nombre inestable rompe el cliente generado si el archivo se mueve.
        """
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "ChatbotRead" in schemas, (
            "Schema 'ChatbotRead' no encontrado.\n"
            "Schemas de chatbot presentes: "
            + str([k for k in schemas if "chatbot" in k.lower()])
            + "\nSolución (CF.1.4): renombrar la clase ChatbotOut -> ChatbotRead "
            "en server/app/routers/hub_chatbots_router.py"
        )

    def test_organizacion_read_schema_has_stable_name(self):
        """El schema de respuesta de Organización debe llamarse 'OrganizacionRead'."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "OrganizacionRead" in schemas, (
            "Schema 'OrganizacionRead' no encontrado.\n"
            "Schemas de organización presentes: "
            + str([k for k in schemas if "organizacion" in k.lower()])
            + "\nSolución: exponer OrganizacionRead "
            "en server/app/routers/hub_organizaciones_router.py"
        )

    def test_llmconfig_read_schema_has_stable_name(self):
        """El schema de respuesta de LLMConfig debe llamarse 'LLMConfigRead'."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "LLMConfigRead" in schemas, (
            "Schema 'LLMConfigRead' no encontrado.\n"
            "Schemas de llm presentes: "
            + str([k for k in schemas if "llm" in k.lower()])
            + "\nSolución (CF.1.4): renombrar LLMConfigOut -> LLMConfigRead "
            "en server/app/routers/hub_llm_configs_router.py"
        )

    def test_prompt_template_read_schema_has_stable_name(self):
        """El schema de respuesta de PromptTemplate debe llamarse 'PromptTemplateRead'."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "PromptTemplateRead" in schemas, (
            "Schema 'PromptTemplateRead' no encontrado.\n"
            "Schemas de prompt presentes: "
            + str([k for k in schemas if "prompt" in k.lower()])
            + "\nSolución (CF.1.4): renombrar PromptTemplateOut -> PromptTemplateRead "
            "en server/app/routers/hub_prompt_templates_router.py"
        )

    # -- Enum de retrieval_mode --

    def test_retrieval_mode_is_an_open_string_not_an_enum(self):
        """PLG.1 **invierte** este test a conciencia, y conviene entender por qué.

        Se llamaba `test_retrieval_mode_has_enum_values` y exigía lo contrario: que el contrato
        expusiera `Literal['RAG', 'MD_LONG_CONTEXT', 'MD_AGENT_SELECTOR']`. Su argumento era
        bueno para su momento (CF.1.4): el frontend llevaba esa lista *hardcodeada*, y un enum en
        el contrato impedía que se desalinearan.

        Desde PLG.1 la lista **no se puede conocer en tiempo de compilación**: un modo de
        recuperación llega instalando un paquete, así que la verdad depende de lo que haya
        instalado en ESA máquina. Un enum en el contrato sería una promesa falsa — y peor: FastAPI
        rechazaría un modo válido antes de que la validación pudiera verlo.

        Lo que sustituye a la garantía vieja NO es «nada»: el modo se valida contra el registro
        vivo (`validar_modo`, 422 con las opciones) y la lista llega al panel por el endpoint de
        opciones de PLG.3. La comprobación se mueve de compilación a ejecución porque el dato
        también se movió.
        """
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        prop = schemas.get("ChatbotCreate", {}).get("properties", {}).get("retrieval_mode", {})

        assert prop.get("type") == "string", f"Definicion actual: {prop}"
        assert "enum" not in prop, (
            "El contrato vuelve a cerrar `retrieval_mode` con un enum. Mientras lo tenga, un "
            "pipeline aportado por un paquete instalado no se puede seleccionar: FastAPI lo "
            "rechaza antes de llegar a `validar_modo`."
        )

    # -- Campos de los Read schemas (verificación de contenido, no de nombre) --

    def test_chatbot_read_fields_are_complete(self):
        """El schema de respuesta de Chatbot (sea cual sea su nombre actual) tiene los campos
        que el frontend espera en su interfaz Chatbot manual."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})

        # Buscar por nombre estable o por el nombre actual con módulo
        read_schema = schemas.get("ChatbotRead") or schemas.get(
            next((k for k in schemas if "hub_chatbots" in k), ""), {}
        )
        props = set(read_schema.get("properties", {}).keys())

        expected = {
            "id", "name", "organizacion_id", "llm_config_id", "system_prompt",
            "sources", "is_active", "retrieval_mode", "retrieval_top_k",
            "use_prompt_caching", "cache_ttl", "kind", "parent_chatbot_id",
            "created_at", "updated_at",
        }
        missing = expected - props
        assert not missing, (
            f"Campos faltantes en el schema de respuesta de Chatbot: {sorted(missing)}"
        )

    def test_organizacion_read_fields_are_complete(self):
        """El schema de respuesta de Organización tiene los campos que el frontend espera."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})

        read_schema = schemas.get("OrganizacionRead") or schemas.get(
            next((k for k in schemas if "hub_organizaciones" in k), ""), {}
        )
        props = set(read_schema.get("properties", {}).keys())

        # `theme_config` salió en PLAT.7: era una copia JSONB que no leía nadie, y la
        # identidad visual se configura en /plataforma/identidad-visual desde PLAT.6.
        expected = {
            "id", "name", "partner_id", "is_active",
            "chatbot_count", "created_at", "updated_at",
        }
        missing = expected - props
        assert not missing, (
            f"Campos faltantes en el schema de respuesta de Organización: {sorted(missing)}"
        )

    def test_llmconfig_read_fields_are_complete(self):
        """El schema de respuesta de LLMConfig tiene los campos que el frontend espera."""
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})

        read_schema = schemas.get("LLMConfigRead") or schemas.get(
            next((k for k in schemas if "hub_llm_configs" in k), ""), {}
        )
        props = set(read_schema.get("properties", {}).keys())

        expected = {
            "id", "provider", "model_name", "temperature",
            "top_p", "max_tokens", "api_key_secret_name", "tier", "label", "is_default",
        }
        missing = expected - props
        assert not missing, (
            f"Campos faltantes en el schema de respuesta de LLMConfig: {sorted(missing)}"
        )


class TestOpenAPIResponseTypesForFrontend:
    """CAL.2 (RED) — Los endpoints que consume el panel de administración declaran
    `response_model`.

    Sin `response_model`, FastAPI documenta la respuesta como un objeto vacío, Orval
    genera `Promise<unknown>` y el frontend no tiene más remedio que redeclarar la
    forma del dato a mano. Eso es exactamente lo que hacían los cinco módulos de
    `shared/api/*.ts` que CAL.2 retira, y lo que prohíbe la regla maestra 4: los tipos
    del frontend salen del contrato, no de una interfaz escrita en paralelo.

    Mientras estos tests estén en rojo, migrar a los hooks de Orval no elimina el tipo
    hardcodeado: solo lo mueve de sitio.
    """

    def _schemas(self) -> dict:
        return app.openapi().get("components", {}).get("schemas", {})

    def _response_ref(self, path: str, method: str) -> str:
        """Devuelve el $ref del 200/202 de un endpoint, o '' si no lo declara."""
        operation = app.openapi()["paths"][path][method]
        content = (
            operation.get("responses", {}).get("200")
            or operation.get("responses", {}).get("202")
            or {}
        ).get("content", {})
        return content.get("application/json", {}).get("schema", {}).get("$ref", "")

    # -- Ingesta: la superficie que consume DocumentsPage --

    def test_ingestion_job_schema_exists(self):
        """El job de ingesta es un tipo del contrato, no una interfaz del frontend.

        Es el caso más claro: `IngestionJob` estaba declarado a mano en
        `frontend/src/shared/api/ingestion.ts` con nueve campos copiados del ORM.
        """
        schemas = self._schemas()
        assert "IngestionJob" in schemas, (
            "Schema 'IngestionJob' no encontrado en el contrato.\n"
            "Schemas de ingesta presentes: "
            + str(sorted(k for k in schemas if "ingestion" in k.lower()))
            + "\nSolución (CAL.2): declarar response_model en GET "
            "/api/v1/hub/ingestion/{chatbot_id}/jobs"
        )

    def test_ingestion_job_fields_are_complete(self):
        """`IngestionJob` trae los campos que la tabla de jobs pinta."""
        job = self._schemas().get("IngestionJob", {})
        props = set(job.get("properties", {}).keys())
        expected = {
            "id", "chatbot_id", "source_url", "original_filename", "canonical_url",
            "status", "chunks_processed", "error_message", "created_at",
        }
        missing = expected - props
        assert not missing, f"Campos faltantes en IngestionJob: {sorted(missing)}"

    def test_document_schemas_exist(self):
        """Documento del corpus: resumen para la tabla y detalle con markdown."""
        schemas = self._schemas()
        for name in ("HubDocumentOut", "HubDocumentDetailOut"):
            assert name in schemas, (
                f"Schema '{name}' no encontrado en el contrato.\n"
                "Schemas de documento presentes: "
                + str(sorted(k for k in schemas if "document" in k.lower()))
                + "\nSolución (CAL.2): declarar response_model en los endpoints de "
                "/api/v1/hub/ingestion/{chatbot_id}/documents"
            )

    def test_document_detail_carries_markdown(self):
        """El detalle es lo que alimenta el modal de preview: lleva el markdown."""
        detail = self._schemas().get("HubDocumentDetailOut", {})
        assert "markdown_content" in detail.get("properties", {}), (
            "HubDocumentDetailOut no expone markdown_content; el modal de preview "
            "quedaría sin contrato que lo respalde."
        )

    def test_ingestion_endpoints_declare_a_response_schema(self):
        """Ningún endpoint de ingesta consumido por la UI responde `unknown`."""
        sin_contrato = [
            f"{method.upper()} {path}"
            for path, method in (
                ("/api/v1/hub/ingestion/{chatbot_id}/jobs", "get"),
                ("/api/v1/hub/ingestion/{chatbot_id}/documents", "get"),
                ("/api/v1/hub/ingestion/{chatbot_id}/documents/{document_id}", "get"),
                ("/api/v1/hub/ingestion/{chatbot_id}/documents/{document_id}", "delete"),
                ("/api/v1/hub/ingestion/upload", "post"),
                ("/api/v1/hub/ingestion/{chatbot_id}/jobs/{job_id}", "delete"),
                ("/api/v1/hub/ingestion/{chatbot_id}/chunks", "delete"),
            )
            if not self._response_ref(path, method)
        ]
        assert not sin_contrato, (
            "Estos endpoints no declaran response_model, así que Orval los genera como "
            f"Promise<unknown>: {sin_contrato}"
        )

    # -- Feedback: la superficie que consume RevisionInteraccionesPage --

    def test_interaction_review_schema_exists(self):
        """La interacción para revisión humana es un tipo del contrato."""
        schemas = self._schemas()
        assert "InteractionReviewOut" in schemas, (
            "Schema 'InteractionReviewOut' no encontrado.\n"
            "Solución (CAL.2): declarar response_model en GET "
            "/api/v1/hub/feedback/{chatbot_id}/review"
        )

    def test_interaction_review_fields_are_complete(self):
        """Lleva los campos que RevisionInteraccionesPage tabula y exporta a CSV."""
        review = self._schemas().get("InteractionReviewOut", {})
        props = set(review.get("properties", {}).keys())
        expected = {
            "id", "user_message", "assistant_message",
            "feedback_score", "feedback_text", "run_id", "created_at",
        }
        missing = expected - props
        assert not missing, f"Campos faltantes en InteractionReviewOut: {sorted(missing)}"

    # -- LLM configs: los dos endpoints que quedaron sin tipar --

    def test_llm_config_auxiliary_schemas_exist(self):
        """Modelos disponibles y prueba de conexión, los dos huecos de hub-llm-configs.

        El resto del router ya declara `response_model`; estos dos se quedaron fuera y
        son justo los que `LLMConfigsPage` consume para poblar el desplegable de modelos
        y para pintar el resultado del botón de probar conexión.
        """
        schemas = self._schemas()
        for name in ("AvailableModelsOut", "LLMConnectionTestOut"):
            assert name in schemas, (
                f"Schema '{name}' no encontrado en el contrato.\n"
                "Solución (CAL.2): declarar response_model en "
                "/api/v1/hub/llm-configs/available-models/{provider_id} y "
                "/api/v1/hub/llm-configs/{config_id}/test"
            )
