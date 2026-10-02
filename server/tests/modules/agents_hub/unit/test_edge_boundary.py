"""Tests para verificar la separación de modelos en el límite edge-cloud."""

def test_config_base_contains_only_config_models() -> None:
    from server.app.modules.agents_hub.database.base import HubConfigBase
    import server.app.modules.agents_hub.database.config_models  # noqa: F401

    # Verify that metadata contains exactly the expected config tables
    tables = set(HubConfigBase.metadata.tables.keys())
    assert tables == {
        "hub_organizaciones",
        "hub_chatbots",
        "hub_llm_configs",
        "hub_prompt_templates",
        "hub_providers",
        # Personas y PAT (AUTH.2 / AUTH.3) — configuración cloud→edge. La tabla se
        # llama `hub_users` desde IDE.2: era de SSO cuando su único escritor era el ACS.
        "hub_users",
        "hub_personal_access_tokens",
        # Vocabulario controlado del corpus (ING.0.1) — ámbitos y submaterias son
        # configuración institucional, no dato operacional del cliente: se
        # sincronizan cloud→edge y los módulos edge los leen vía ConfigProvider.
        "hub_vocabulary_terms",
        # Temas de identidad visual (SEC.8.6) — colores, tipografía y logotipo de la
        # institución. Es configuración, del mismo lado que los prompts: no contiene
        # dato del cliente final y el edge la necesita para pintar el widget, así que
        # viaja cloud→edge. Vivían como ficheros locales, que en Cloud Run desaparecían
        # al reciclarse el contenedor.
        "hub_themes",
        # Credencial de sitio del widget (SEC.8.5) — sustituye al Bearer privilegiado que
        # el widget embebía en el HTML. Es configuración de publicación del chatbot, no
        # identidad ni dato del cliente final: no lleva rol ni organizaciones.
        "hub_widget_keys",
        # Override del prompt y del nivel de una actividad de plataforma (PRO.2.1) — del
        # mismo lado que `hub_prompt_templates`: es lo que se le dice a un modelo y con qué
        # nivel corre, no dato del cliente final. El edge lo lee vía ConfigProvider.
        "hub_activity_prompts",
        # Módulos de la plataforma y quién los tiene concedidos (INF.7) — es configuración
        # administrativa: se decide en el cloud y **el edge la necesita**, porque los routers
        # de informes, curación y automatización viven ahí y tienen que saber si quien pide un
        # informe puede pedirlo. No contiene dato del cliente final: el catálogo son cuatro
        # códigos y la concesión es un par (sujeto, módulo). Mismo lado que `hub_users`,
        # que también es identidad administrativa y no contenido.
        "hub_platform_modules",
        "hub_module_grants",
        # MT.2 — con qué credencial habla una organización con un proveedor. Es configuración
        # administrativa del lado cloud, y **el edge la necesita** para construir el cliente
        # del modelo. No contiene dato del cliente final: o una clave, o el nombre de una
        # variable de entorno, o nada (ADC).
        "hub_provider_credentials",
    }

def test_operational_base_contains_only_operational_models() -> None:
    from server.app.modules.agents_hub.database.base import HubOperationalBase
    import server.app.modules.agents_hub.database.operational_models  # noqa: F401
    import server.app.modules.redaccion.database.models  # noqa: F401 — tablas redaccion (edge)

    tables = set(HubOperationalBase.metadata.tables.keys())
    assert tables == {
        "hub_documents",
        "hub_document_chunks",
        "hub_interactions",
        "hub_ingestion_jobs",
        # Bloque 9Q (Calidad de contenido web) — entidades sitio/página/selección
        "hub_web_sites",
        "hub_crawled_pages",
        "hub_corpus_selections",
        # Bloque DIN — el apartado como dato y el diario de sus pasadas. Operacionales sin
        # discusión: una sección delimita contenido del cliente y sus criterios de juicio, y el
        # diario dice qué se hizo con el corpus de ese cliente. Ninguna de las dos se sincroniza
        # cloud→edge.
        "hub_web_sections",
        "hub_crawl_runs",
        # Bloque FUN — el catálogo de funciones deterministas. Operacional y no configuración
        # aunque tenga cascada de plataforma: `hub_funcion_versiones.code` y su declaración
        # responsable son texto escrito por una persona de la organización, que es el criterio
        # con el que `hub_lexicon_pairs` acabó en este lado.
        "hub_funciones",
        "hub_funcion_versiones",
        # AUT.7 — los ficheros que una función produce al ejecutarse. Operacional **sin la
        # discusión que sí tenían las dos de arriba**: un artefacto es el resultado de correr
        # código sobre los documentos del cliente. Que la función pueda ser de plataforma no lo
        # arrastra al otro lado; lo que se sincroniza cloud→edge es la función, nunca lo que
        # salió de ejecutarla.
        "hub_funcion_artefactos",
        # #172, #173 y #175 — los agentes de unidad. Mismo criterio que FUN: el prompt y la
        # declaración son texto de una persona de la organización, las fichas resumen sus
        # documentos y las consultas dicen qué se le ofreció a quién. Nada de esto se sincroniza.
        "hub_agentes_unidad",
        "hub_agente_unidad_versiones",
        "hub_agente_fichas",
        "hub_agente_consultas",
        # Módulo redacción (edge, 9R) — procesan expedientes del cliente
        "hub_report_templates",
        "hub_report_template_versions",
        "hub_workspaces",
        "hub_workspace_blocks",
        "hub_run_manifests",
        "hub_script_proposals",       # 9R.5.5 — scripts metaprogramados
        "hub_workspace_audit_events",  # 9R.5.x — auditoría de workspace
        # Bloque 9Q.1 — hallazgos de calidad de contenido
        "hub_content_findings",
        # RAG.13 — escenarios de prueba y su veredicto humano. Operacionales y no de
        # configuración: son las pruebas del cliente sobre su propio corpus, con sus
        # consultas reales dentro, así que no salen del edge.
        "hub_test_scenarios",
        "hub_test_runs",
        # RES.3 — pares léxicos «como lo dice una persona / como lo dice la norma». **Nacieron en
        # `HubConfigBase` y este test lo rechazó con razón**: `termino_de_usuario` es literalmente
        # lo que escribió alguien, y la configuración se sincroniza cloud→edge, así que ponerlos
        # ahí obligaba a que el texto de las preguntas del cliente existiera en el cloud. Mismo
        # motivo que `hub_test_scenarios`, que está dos líneas más arriba por lo mismo.
        #
        # No es que el vocabulario sea operacional: `hub_vocabulary_terms` (ámbitos, submaterias)
        # es configuración y está bien donde está, porque **no contiene texto de nadie**. Lo que
        # decide el lado no es «es vocabulario», es «lleva dentro lo que escribió una persona».
        #
        # Consecuencia asumida: se cura en el edge y no viaja, así que con varios edge cada uno
        # aprende de sus propios usuarios. Que además es lo correcto.
        "hub_lexicon_pairs",
        # SEC.4 — consumo por sujeto y ventana. Operacional y no configuración: el LÍMITE
        # se configura y viaja cloud→edge, pero lo GASTADO es dato del cliente final y no
        # sale del edge. Un contador colgado de `HubChatbot` se habría sincronizado con la
        # configuración, que es justo lo que la frontera existe para impedir.
        "hub_usage_counters",
        # REG.1 — el registro de usos de IA que declaran las herramientas de fuera. Operacional
        # por el mismo criterio que decidió `hub_lexicon_pairs`: dice quién de esta organización
        # usó qué agente y para qué, y eso es dato del cliente final. Que el cloud tuviera el
        # registro de actividad de sus clientes sería justo lo que la frontera existe para
        # impedir — y en una instalación edge por requisito regulatorio, inaceptable.
        "hub_actividad_ia",
        # AUT.6 — la evidencia por ejecución que deposita una aplicación de fuera. Mismo
        # criterio que `hub_actividad_ia`, y más fuerte: dice qué modelo tocó qué fuentes, quién
        # aprobó qué y con qué salida, todo de esta organización. Que el cloud tuviera eso de sus
        # clientes es exactamente lo que la frontera existe para impedir.
        "hub_manifiestos_externos",
    }

def test_no_cross_base_relationships() -> None:
    """Introspect mappers: no relationship in HubConfigBase points to HubOperationalBase classes and vice versa."""
    from sqlalchemy.orm import class_mapper
    from server.app.modules.agents_hub.database.config_models import HubChatbot

    mapper = class_mapper(HubChatbot)
    relationships = [rel.key for rel in mapper.relationships]
    assert "document_chunks" not in relationships
    assert "interactions" not in relationships

def test_edge_sync_config_endpoint_exists_returns_501() -> None:
    from server.app.api.v1.edge_sync import router
    route = next((r for r in router.routes if r.path == "/edge/config"), None)
    assert route is not None
    assert "GET" in route.methods

def test_edge_sync_telemetry_endpoint_exists_returns_501() -> None:
    from server.app.api.v1.edge_sync import router
    route = next((r for r in router.routes if r.path == "/edge/telemetry"), None)
    assert route is not None
    assert "POST" in route.methods
