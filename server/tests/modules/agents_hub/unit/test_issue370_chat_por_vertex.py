"""#370 — los modelos de conversación pueden ir por Vertex, con ADC y la región de su proveedor.

La API de Gemini de AI Studio factura por prepago: el 05-11 se agotaron los créditos y todos los
apartados de IA de los informes fallaron con un 402. Vertex factura al proyecto de GCP, y
embeddings y reranker ya iban por ahí; el chat no, porque `_build_model` no conocía el tipo
`google_vertexai`.

Lo que más importa vigilar no es la rama, sino **qué credencial acaba usando**: en producción
`GOOGLE_API_KEY` sigue en el entorno, y si el SDK la recoge en modo Vertex («express») la
llamada vuelve a ir contra la clave sin saldo, con el mismo 402 y sin que nada lo delate.
"""
from unittest.mock import Mock, patch

import pytest

from server.app.modules.agents_hub.services.embedding_service import REGION_VERTEX_POR_DEFECTO


def _config_vertex(location: str | None):
    return Mock(
        provider="vertex",
        model_name="gemini-2.5-pro",
        temperature=0.2,
        top_p=1.0,
        max_tokens=4096,
        api_key_secret_name=None,
        provider_rel=Mock(
            id="vertex",
            provider_type="google_vertexai",
            api_key=None,
            base_url=None,
            location=location,
        ),
    )


_FACTORIA = "server.app.modules.agents_hub.services.model_factory.ChatGoogleGenerativeAI"


class TestRamaVertex:
    def test_usa_vertex_con_el_proyecto_y_la_region_del_proveedor(self, monkeypatch):
        from server.app.modules.agents_hub.services.model_factory import _build_model

        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto-x")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-southwest1")
        with patch(_FACTORIA) as cls:
            _build_model(_config_vertex("global"))

        kwargs = cls.call_args.kwargs
        assert kwargs["vertexai"] is True
        assert kwargs["project"] == "proyecto-x"
        # La del proveedor gana a la del entorno: Argon solo responde en `global`.
        assert kwargs["location"] == "global"
        assert kwargs["model"] == "gemini-2.5-pro"
        assert kwargs["max_output_tokens"] == 4096
        assert "google_api_key" not in kwargs

    def test_sin_region_en_el_proveedor_usa_la_del_entorno(self, monkeypatch):
        from server.app.modules.agents_hub.services.model_factory import _build_model

        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto-x")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")
        with patch(_FACTORIA) as cls:
            _build_model(_config_vertex(None))

        assert cls.call_args.kwargs["location"] == "europe-west4"

    def test_sin_region_en_ninguna_parte_usa_la_de_los_embeddings(self, monkeypatch):
        from server.app.modules.agents_hub.services.model_factory import _build_model

        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto-x")
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
        with patch(_FACTORIA) as cls:
            _build_model(_config_vertex(None))

        assert cls.call_args.kwargs["location"] == REGION_VERTEX_POR_DEFECTO

    def test_sin_proyecto_falla_diciendo_cual_falta(self, monkeypatch):
        from server.app.modules.agents_hub.services.model_factory import _build_model

        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
            _build_model(_config_vertex("global"))

    def test_la_clave_de_ai_studio_del_entorno_no_se_cuela(self, monkeypatch):
        """Sin dobles: el cliente real del SDK, construido sin red."""
        from server.app.modules.agents_hub.services.model_factory import _build_model

        monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-ai-studio-sin-saldo")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto-x")
        modelo = _build_model(_config_vertex("global"))

        cliente = modelo.client._api_client
        assert cliente.vertexai is True
        assert cliente.project == "proyecto-x"
        assert cliente.location == "global"
        assert cliente.api_key is None


class TestProveedoresSembrados:
    def test_vertex_global_existe_para_los_modelos_que_solo_estan_ahi(self):
        from server.app.modules.agents_hub.database.seeds import _DEFAULT_PROVIDERS

        por_id = {p.id: p for p in _DEFAULT_PROVIDERS}
        assert por_id["vertex-global"].provider_type == "google_vertexai"
        assert por_id["vertex-global"].location == "global"
        # Que salga de la UE se tiene que leer en el panel, no solo en la base.
        assert "UE" in por_id["vertex-global"].name

    def test_vertex_sigue_en_la_region_del_entorno(self):
        from server.app.modules.agents_hub.database.seeds import _DEFAULT_PROVIDERS

        por_id = {p.id: p for p in _DEFAULT_PROVIDERS}
        assert por_id["vertex"].location is None
