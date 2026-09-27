"""Issue #169 — no se responde «encolado» sin encolar.

**El defecto.** `POST /{workspace_id}/re-analyze` devolvía **202 Accepted** con
`status: "queued"` y su docstring prometía «dispara `InitAnonymizationNode` sin llegar al LLM; el
análisis se encola en background». Lo que hacía era escribir un evento de auditoría y volver. No
había `BackgroundTasks`, ni cola, ni se instanciaba el nodo — y **nadie consumía el evento**
`re_analyze_started`: `grep` sobre `server/app` sólo lo encontraba donde se escribía.

**Por qué era peor que no tener el botón.** Las otras tres capas que la issue #98 destapó no
hacían nada **y no decían nada**. Ésta **afirmaba haber hecho algo**: quien pulsaba recibía
«aceptado, encolado», la pantalla no daba error, y el análisis no existía. Es la misma forma que
costó dos horas de alerta inerte en el despliegue, cuando un POST fallaba y el guion imprimía
«[creada]» descartando la respuesta.

**Y el test que lo dejó pasar se llamaba `test_re_analyze_triggers_init_node_without_llm`.**
Afirmaba en su nombre que dispara el nodo y lo único que comprobaba era que la respuesta traía
`202` y `"queued"` — o sea, **fijaba la forma de la mentira**. Un test que comprueba el contrato
de una promesa sin comprobar que se cumple es peor que no tenerlo: da confianza.

**Cómo se cierra, y por qué no se implementa la cola.** La finalidad real del botón, según quien
lo pidió, es **ver el resultado** de una anonimización ya aplicada, o el de la iteración
anterior. Eso ya lo sirve `GET /{workspace_id}/anonymization-summary`: desde la #98 cada
ejecución escribe su resumen en el manifiesto, así que la pantalla siempre puede mostrar el de la
última pasada.

Así que el endpoint sobra y la funcionalidad se queda: el botón pasa a refrescar la vista del
resumen, que es lo que de verdad se quería, y deja de existir la ruta que mentía.
"""

from __future__ import annotations

import uuid


def _rutas_de_anonimizacion() -> set[str]:
    from server.app.routers.redaccion.anonymization_router import router

    return {r.path for r in router.routes}  # type: ignore[attr-defined]


class TestLaRutaQueMentiaYaNoExiste:

    def test_no_hay_endpoint_de_re_analisis(self) -> None:
        rutas = _rutas_de_anonimizacion()

        assert not any("re-analyze" in r for r in rutas), (
            "sigue existiendo `POST /re-analyze`. Respondía 202 «encolado» sin encolar nada: "
            "ni `BackgroundTasks`, ni cola, ni `InitAnonymizationNode`. Si algún día hace falta "
            "un análisis de verdad, se implementa con la cola antes de anunciarla."
        )

    def test_el_dto_de_la_respuesta_tampoco(self) -> None:
        """El contrato se regenera desde el código: un DTO huérfano reaparecería en el cliente."""
        import server.app.routers.redaccion.anonymization_router as modulo

        assert not hasattr(modulo, "ReAnalyzeResponse"), (
            "queda el DTO de una respuesta que ya no se emite; el cliente generado lo "
            "arrastraría y volvería a parecer que la operación existe"
        )


class TestLoQueSiSeConserva:
    """Retirar la ruta no puede llevarse por delante la finalidad que el botón sí cumplía."""

    def test_el_resumen_se_sigue_pudiendo_consultar(self) -> None:
        rutas = _rutas_de_anonimizacion()

        assert any("anonymization-summary" in r for r in rutas), (
            "sin esta ruta no hay forma de ver el resultado de la anonimización, que es "
            "exactamente para lo que se quería el botón"
        )

    def test_el_modo_se_sigue_pudiendo_cambiar(self) -> None:
        rutas = _rutas_de_anonimizacion()

        assert any("anonymization-mode" in r for r in rutas)


class TestElGuardarrailMiraLoQueDice:
    """Un test que recorre algo y no encuentra nada pasa en verde sin haber mirado."""

    def test_sabe_leer_las_rutas_del_router(self) -> None:
        rutas = _rutas_de_anonimizacion()

        assert len(rutas) >= 2, f"sólo se ven {len(rutas)} rutas: este test no está mirando nada"
        assert all(r.startswith("/redaccion/workspaces") for r in rutas), rutas

    def test_el_identificador_de_workspace_sigue_en_las_rutas(self) -> None:
        """Si el prefijo cambiara, los asserts de arriba dejarían de significar lo que dicen."""
        rutas = _rutas_de_anonimizacion()
        uuid.uuid4()  # sólo para dejar claro que las rutas son por workspace

        assert any("{workspace_id}" in r for r in rutas)
