"""Tests RAG.6b — el adaptador real del Ranking API de Vertex.

RAG.6a dejó el mecanismo verificado con un reranker determinista. Lo que faltaba es el
adaptador contra el servicio de verdad, y el plan avisa de por qué no vale probarlo solo
contra un doble: este proyecto ya se comió tres veces la misma familia de fallo —un
`GoogleEmbeddingService` inalcanzable durante meses, una guarda de dimensión que no podía
saltar y su test verificando un campo inventado—, y las tres pasaban los tests.

Así que aquí se fija lo que se **midió contra el servicio real** el 2026-08-24 con el proyecto
`uji-teclab`, y cada test dice qué comportamiento observado protege:

- **Los scores del Ranking API ya vienen en [0,1]**, no son logits. Medidos: 0,7944 / 0,0504 /
  0,01 sobre tres candidatos en valenciano. Pasarlos por la sigmoide de `normalize_score`
  —que es la correcta para el cross-encoder local— los aplastaría hacia 0,5 y destruiría
  justo la separación que hace útil al reranker: un 0,01 se convertiría en 0,502, y el packer
  de RAG.5 y el quality gate decidirían sobre números sin rango.
- **El valenciano funciona.** Era el riesgo abierto del prompt: Google declara 25 idiomas y no
  publica cuáles, y el catalán no aparece. Con la consulta de ORI-05 el documento correcto
  saca 0,7944 y el señuelo —el Reglament del Consell de l'Estudiantat, que es exactamente
  donde ORI-19 se equivocó— saca 0,0504.
- **La petición es asíncrona.** `AGENTS.md` prohíbe I/O síncrona en el servidor, así que el
  adaptador habla por `httpx.AsyncClient` y no por el cliente síncrono de la librería de
  Google, que obligaría a envolverlo en un hilo.
"""
from __future__ import annotations


import pytest

from server.app.modules.agents_hub.services.reranker import (
    PROVIDER_TYPE_VERTEX_RANKING,
    VertexRankingReranker,
    normalize_score,
)


class _RespuestaFalsa:
    """Lo que devuelve el Ranking API, copiado de una respuesta real."""

    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _ClienteFalso:
    """Sustituye a httpx.AsyncClient y guarda lo que se le pidió."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.peticiones: list[tuple[str, dict, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, headers=None):
        self.peticiones.append((url, json, headers or {}))
        return _RespuestaFalsa(self._payload)


def _payload(*pares: tuple[str, float]) -> dict:
    return {
        "records": [
            {"id": ident, "content": f"contenido {ident}", "score": score}
            for ident, score in pares
        ]
    }


def _reranker(cliente, **kwargs) -> VertexRankingReranker:
    return VertexRankingReranker(
        project="uji-teclab",
        credenciales=_CredencialFalsa(),
        cliente_factory=lambda: cliente,
        **kwargs,
    )


class _CredencialFalsa:
    token = "ya29.token-de-prueba"
    valid = True
    expired = False

    def refresh(self, _peticion) -> None:
        return None


class TestContratoMedidoContraElServicioReal:

    @pytest.mark.asyncio
    async def test_should_keep_the_api_scores_without_applying_the_sigmoid(self):
        """El fallo que este test existe para impedir.

        Los tres valores son los que devolvió el servicio real. Si alguien "unifica" la
        normalización aplicando `normalize_score` también aquí, el 0,01 pasa a 0,502 y el
        candidato irrelevante entra en el contexto con aspecto de mediano.
        """
        cliente = _ClienteFalso(_payload(("0", 0.7944), ("1", 0.0504), ("2", 0.01)))

        resultados = await _reranker(cliente).rerank("q", ["A", "B", "C"], top_k=3)

        assert [r.score for r in resultados] == [0.7944, 0.0504, 0.01]
        assert normalize_score(0.01) != pytest.approx(0.01), (
            "si esto falla, normalize_score ha cambiado y el test ya no prueba nada"
        )

    @pytest.mark.asyncio
    async def test_should_map_api_ids_back_to_input_positions(self):
        """El API devuelve los registros reordenados; el protocolo habla de índices de la
        lista de entrada. Perder ese mapeo mete en el contexto un texto distinto del que se
        puntuó, y el síntoma serían citas que no corresponden a la respuesta."""
        cliente = _ClienteFalso(_payload(("2", 0.9), ("0", 0.5), ("1", 0.1)))

        resultados = await _reranker(cliente).rerank("q", ["A", "B", "C"], top_k=3)

        assert [r.index for r in resultados] == [2, 0, 1]

    @pytest.mark.asyncio
    async def test_should_respect_top_k(self):
        cliente = _ClienteFalso(_payload(("0", 0.9), ("1", 0.5), ("2", 0.1)))

        resultados = await _reranker(cliente).rerank("q", ["A", "B", "C"], top_k=2)

        assert len(resultados) == 2
        assert cliente.peticiones[0][1]["topN"] == 2

    @pytest.mark.asyncio
    async def test_should_send_the_measured_model_and_ranking_config(self):
        """`semantic-ranker-default-004` no es una preferencia: las variantes -003 y -002 son
        de 512 tokens y el chunker produce ~1.000, así que truncarían medio fragmento."""
        cliente = _ClienteFalso(_payload(("0", 0.9)))

        await _reranker(cliente).rerank("q", ["A"], top_k=1)

        url, cuerpo, cabeceras = cliente.peticiones[0]
        assert "projects/uji-teclab/locations/global" in url
        assert url.endswith("rankingConfigs/default_ranking_config:rank")
        assert cuerpo["model"] == "semantic-ranker-default-004"
        assert cuerpo["query"] == "q"
        assert cabeceras["Authorization"] == "Bearer ya29.token-de-prueba"

    @pytest.mark.asyncio
    async def test_should_send_every_candidate_with_a_stable_id(self):
        cliente = _ClienteFalso(_payload(("0", 0.9), ("1", 0.1)))

        await _reranker(cliente).rerank("consulta", ["primero", "segundo"], top_k=2)

        registros = cliente.peticiones[0][1]["records"]
        assert [r["id"] for r in registros] == ["0", "1"]
        assert [r["content"] for r in registros] == ["primero", "segundo"]

    @pytest.mark.asyncio
    async def test_should_return_empty_without_calling_the_api_when_there_are_no_candidates(
        self,
    ):
        """Cobrar una llamada para reordenar nada es tirar dinero, y el API rechaza la
        petición sin registros."""
        cliente = _ClienteFalso(_payload())

        resultados = await _reranker(cliente).rerank("q", [], top_k=5)

        assert resultados == []
        assert cliente.peticiones == []

    @pytest.mark.asyncio
    async def test_should_fail_loudly_without_project(self):
        """Mismo criterio que `VertexEmbeddingService`: el proyecto se comprueba antes de
        llamar, y el mensaje dice qué hacer."""
        with pytest.raises(RuntimeError) as error:
            VertexRankingReranker(project="", credenciales=_CredencialFalsa())

        assert "GOOGLE_CLOUD_PROJECT" in str(error.value)


class TestResolucionPorConfiguracion:

    @pytest.mark.asyncio
    async def test_should_resolve_the_vertex_reranker_from_the_configuration(
        self, db_session, monkeypatch
    ):
        """El proveedor y el modelo son configuración, no constantes: es lo que permite
        cambiar de reranker sin tocar código.

        `GOOGLE_CLOUD_PROJECT` se pone aquí y no se hereda del entorno: el constructor lo exige
        (`test_should_fail_loudly_without_project`), así que sin esta línea el test pasa en la
        máquina de quien tiene `gcloud` configurado y falla en CI, que no lo tiene. Un test que
        depende del entorno del desarrollador mide el entorno, no el código.
        """
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto-de-prueba")

        from server.app.modules.agents_hub.database.config_models import (
            HubLLMConfig,
            HubProvider,
        )
        from server.app.modules.agents_hub.services.reranker import resolve_reranker

        await db_session.merge(
            HubProvider(
                id="vertex-rank",
                name="Vertex AI Ranking",
                provider_type=PROVIDER_TYPE_VERTEX_RANKING,
            )
        )
        db_session.add(
            HubLLMConfig(
                provider="vertex-rank",
                model_name="semantic-ranker-default-004",
                purpose="rerank",
                is_default=True,
            )
        )
        await db_session.commit()

        reranker = await resolve_reranker(db_session, credenciales=_CredencialFalsa())

        assert isinstance(reranker, VertexRankingReranker)
        assert reranker.model_name == "semantic-ranker-default-004"
