"""Issue #98 — el resumen de anonimización **se escribe**, no sólo se sabe escribir.

**El hueco, medido.** En la base de desarrollo: **0 de 35 manifiestos** de ejecución traen un
resumen. La clave `anonymization_summary` está en todos y vale `null` en todos. Y no falla nada,
porque el campo tiene `= None` por defecto en el contrato: `AuditLogNode` —el nodo que cierra cada
ejecución y persiste el manifiesto— construye el `DraftingRunManifest` **sin pasárselo**.

**Por qué nadie lo había notado, y es la parte que importa.** El único sitio del repositorio que
rellenaba el campo era un test, `test_ner_citations_and_manifest.py`, que construye el manifiesto
**a mano** con `anonymization_summary=AnonymizationSummary.from_context(ctx)`. Ese test es bueno
—demuestra que el resumen viaja sin originales ni sintéticos— pero demuestra el **contrato**, no
el **cableado**: un objeto construido a mano no puede decir si alguien lo construye así de verdad.

Es la tercera capa de la misma issue, y las tres son la misma forma: el panel existía y ninguna
ruta lo montaba; el endpoint lo servía y la pantalla lo escondía a quien podía verlo; y ahora el
endpoint lee un dato que nadie escribía. La primera tapaba a la tercera: con el panel inalcanzable,
que el dato faltara no daba síntoma.

Así que esto se comprueba **sobre el nodo**, con su repositorio doblado, y no sobre un manifiesto
escrito a mano.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from server.app.modules.redaccion.contracts.runtime import WorkspaceState
from server.app.modules.redaccion.graph.nodes.audit_log import AuditLogNode
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationMode,
    PiiSpan,
    RunAnonymizationContext,
)


def _estado(contexto=None) -> WorkspaceState:
    return WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={},
        status="assembled",
        warnings=[],
        anonymization_context=contexto,
    )


def _contexto(workspace_id: uuid.UUID) -> RunAnonymizationContext:
    return RunAnonymizationContext(
        workspace_id=workspace_id,
        mode=AnonymizationMode.REPLACE,
        spans=[
            PiiSpan(type="PERSON", original="Juan García", synthetic="Carlos Pérez"),
            PiiSpan(type="EMAIL", original="ana@x.com", synthetic="f@y.com"),
            PiiSpan(type="PERSON", original="Luis Ruiz", synthetic="Pedro Sanz"),
        ],
        forward_map={
            "Juan García": "Carlos Pérez",
            "ana@x.com": "f@y.com",
            "Luis Ruiz": "Pedro Sanz",
        },
        reverse_map={
            "Carlos Pérez": "Juan García",
            "f@y.com": "ana@x.com",
            "Pedro Sanz": "Luis Ruiz",
        },
    )


def _nodo():
    """El nodo con su repositorio y su trazado doblados. Devuelve `(nodo, repo)`."""
    repo = MagicMock()
    repo.save = AsyncMock()
    trazado = MagicMock()
    trazado.open_trace = MagicMock(return_value=MagicMock())
    return AuditLogNode(manifest_repo=repo, tracing_service=trazado), repo


def _persistido(repo):
    """El ORM que el nodo mandó guardar."""
    assert repo.save.await_count == 1, (
        f"el nodo no persistió el manifiesto ({repo.save.await_count} llamadas)"
    )
    return repo.save.await_args.args[0]


class TestElResumenLlegaAlManifiesto:

    async def test_el_manifiesto_persistido_trae_el_resumen(self) -> None:
        nodo, repo = _nodo()
        estado = _estado()
        estado.anonymization_context = _contexto(estado.workspace_id)

        await nodo(estado)

        resumen = (_persistido(repo).payload_json or {}).get("anonymization_summary")
        assert resumen is not None, (
            "`AuditLogNode` cierra la ejecución sin escribir el resumen de anonimización, así "
            "que `GET /anonymization-summary` devuelve 404 siempre y la pantalla dice «no se ha "
            "ejecutado ningún análisis todavía» aunque se hayan sustituido datos personales. "
            "Medido: 0 de 35 manifiestos lo traían."
        )
        assert resumen["total_spans"] == 3
        assert resumen["counts_by_type"] == {"PERSON": 2, "EMAIL": 1}
        assert resumen["mode"] == "replace"

    async def test_sin_contexto_no_se_inventa_un_resumen(self) -> None:
        """`None` significa «no se analizó», y es distinto de «se analizó y no había nada».

        Un resumen con `total_spans: 0` afirmaría que se miró y no se encontró PII. Si el modo
        está en `off` o el nodo de detección no llegó a correr, eso sería mentira — y de las dos
        maneras de equivocarse, ésta es la que tranquiliza.
        """
        nodo, repo = _nodo()

        await nodo(_estado(contexto=None))

        payload = _persistido(repo).payload_json or {}
        assert payload.get("anonymization_summary") is None

    async def test_el_resumen_no_lleva_originales_ni_sinteticos(self) -> None:
        """Lo que el contrato ya garantizaba, comprobado ahora sobre lo que se persiste.

        El manifiesto se guarda en la base y se sirve por API: si los valores se colaran aquí,
        la anonimización estaría deshecha en el sitio donde se audita que se hizo.

        **Primero se exige que el resumen esté**, y no es ceremonia: sin esa línea este test
        pasaba en verde contra el código que no escribía ningún resumen —no había dónde
        filtrarse nada—, o sea que daba por buena la garantía sin haber mirado el dato que dice
        vigilar. Es la forma de guardarraíl que este proyecto ya ha visto fallar varias veces.
        """
        import json

        nodo, repo = _nodo()
        estado = _estado()
        estado.anonymization_context = _contexto(estado.workspace_id)

        await nodo(estado)

        payload = _persistido(repo).payload_json or {}
        assert payload.get("anonymization_summary") is not None, (
            "sin resumen no hay nada que comprobar: este test estaría pasando por ausencia"
        )

        blob = json.dumps(payload, default=str)
        for valor in ("Juan García", "Carlos Pérez", "ana@x.com", "f@y.com", "Luis Ruiz"):
            assert valor not in blob, f"el manifiesto persistido lleva «{valor}»"


class TestElGuardarrailMiraElNodoYNoUnObjetoEscritoAMano:
    """Lo que faltaba no era una comprobación del contrato: era una del cableado."""

    def test_el_nodo_construye_el_resumen_desde_el_estado(self) -> None:
        import inspect

        fuente = inspect.getsource(AuditLogNode.__call__)
        assert "anonymization_summary" in fuente, (
            "`AuditLogNode` no menciona el resumen. El contrato admite el campo con `= None` por "
            "defecto, así que olvidarlo no da error: da un `null` persistido y una pantalla que "
            "dice que no hay análisis."
        )
