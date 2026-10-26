"""DeterministicExtractionNode — ejecuta pipelines de extracción para bloques DETERMINISTIC_DATA (9R.6.2/9R.6.6/9R.5.9)."""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any, cast

from server.app.modules.redaccion.contracts.runtime import ExtractionWarning, WorkspaceState
from server.app.modules.redaccion.pipelines.contracts import ExtractionInput, StorageRef


_SLOT_KIND_TO_SOURCE: dict[str, set[str]] = {
    "excel": {"excel"},
    "pdf":   {"pdf_text", "pdf_table"},
    "text":  {"manual"},
    "csv":   {"excel"},
    # SEG.3 — un documento Markdown con sus tablas hechas. Varios bloques pueden apoyarse en el
    # MISMO fichero: es la forma de estos informes, cuarenta y dos tablas en un documento.
    "markdown": {"md_table"},
}

#: PRO.3 — pipelines que sirven a **cualquier** tipo de slot.
#:
#: Los demás sirven a un tipo concreto —`excel` para hojas de cálculo, `pdf_text` para PDF—,
#: pero un script de extracción es genérico por definición: lee el fichero que la plataforma
#: le pase. Sin esto, un bloque con `source_pipeline='admin_script'` no encontraba artefacto y
#: se quedaba sin fichero que leer.
_PIPELINES_GENERICOS: frozenset[str] = frozenset({"admin_script"})


def _find_artifact_for_pipeline(source_pipeline: str, spec, artifacts_normalized: dict[str, str]) -> StorageRef | None:
    all_slots = list(spec.input_contract.required_slots) + list(spec.input_contract.optional_slots)
    for slot in all_slots:
        matched_pipelines = _SLOT_KIND_TO_SOURCE.get(slot.kind, set())
        acepta = source_pipeline in matched_pipelines or source_pipeline in _PIPELINES_GENERICOS
        if acepta and slot.slot_id in artifacts_normalized:
            # `bucket` vacío y la ruta entera en `key`: los pipelines componen
            # `Path(bucket) / key`, y desde que la normalización materializa el fichero la
            # ruta es absoluta. Partirla por la primera barra daba `Path("C:") / "Users/…"`,
            # que en Windows es una ruta relativa al directorio actual de esa unidad.
            return StorageRef(bucket="", key=artifacts_normalized[slot.slot_id])
    return None


async def _extraer(pipeline, inp):
    """Ejecuta el pipeline por la vía que tenga.

    `AdminScriptExtractionPipeline` sólo expone `extract_async` —habla con el sandbox por
    HTTP—, así que llamarlo por `extract` en un hilo daba `AttributeError` y el bloque acababa
    en `failed` acusando al script de un fallo del cableado.

    La pregunta es si el método es **de verdad** awaitable, no si el nombre existe: un
    `MagicMock` tiene todos los atributos, así que un `hasattr` mandaría a la vía asíncrona a
    cualquier doble de test y el fallo sería «object MagicMock can't be used in 'await'».
    """
    asincrono = getattr(pipeline, "extract_async", None)
    if inspect.iscoroutinefunction(asincrono):
        return await asincrono(inp)
    return await asyncio.to_thread(pipeline.extract, inp)


class DeterministicExtractionNode:
    """Ejecuta la extracción determinista para todos los bloques DETERMINISTIC_DATA del spec.

    En caso de fallo por bloque: marca status=failed(extraction_failed) y continúa
    con el resto (el CoreGraph NO aborta).
    """

    def __init__(self, factory: Any, resolvedor: Any = None, almacen: Any = None) -> None:
        self._factory = factory
        # APER.14 — con el contrato nuevo, una función empaquetada pide su fichero al
        # almacenamiento en vez de abrir la ruta que le den. Sin esto, 
        # diría «no hay almacenamiento» y el bloque fallaría con un motivo de cableado.
        self._almacen = almacen
        # FUN.3 — quien traduce `funcion@versión` en algo ejecutable. Opcional para que un
        # bloque sin función —`excel_pipeline` y compañía— siga funcionando sin catálogo, y
        # porque los tests del nodo que no usan scripts no tienen por qué construirlo.
        self._resolvedor = resolvedor

    async def _resolver_funcion(self, funcion_ref: Any) -> Any:
        """La versión anclada, o un fallo que nombra la función y el motivo."""
        from server.app.modules.redaccion.funciones_resolver import FuncionNoEjecutable

        if self._resolvedor is None:
            raise FuncionNoEjecutable(
                "el bloque referencia una función del catálogo y este grafo se construyó sin "
                "resolutor: el informe no puede ejecutarla"
            )
        return await self._resolvedor.resolver(funcion_ref.funcion_id, funcion_ref.version)

    async def _ejecutar_ejecutable(
        self, ejecutable: Any, *, ficheros: dict[str, str], parametros: dict[str, Any]
    ) -> Any:
        """Ejecuta lo que el resolutor resolvió, por el camino que le corresponde a su origen.

        **La bifurcación mira el origen y no si `code` viene nulo.** Mirar el código funcionaría
        hoy y mentiría el día que un autoservicio guarde su código fuera; el origen es lo que
        dice de qué clase de función se trata, y es lo que el catálogo declara.

        Sin esta bifurcación, una función de paquete mandaba al sandbox el `code=""` que
        `como_opciones_del_pipeline()` devuelve cuando no hay código, y el bloque salía **vacío
        sin error**: el informe se genera y no dice nada. Es el fallo más caro de este bloque
        justamente porque no se ve.
        """
        if getattr(ejecutable, "origen", "autoservicio") == "paquete":
            from server.app.modules.redaccion.funciones_paquete import ejecutar_empaquetada

            return await ejecutar_empaquetada(
                ejecutable.entry_point,
                ficheros=ficheros,
                parametros=parametros,
                almacen=self._almacen,
            )

        raise NotImplementedError(
            "una función de autoservicio se ejecuta por el pipeline del sandbox, que es el "
            "camino de `__call__`; este método sólo enruta lo que no pasa por ahí"
        )

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        updated_blocks = dict(state.blocks)
        new_warnings = list(state.warnings)
        new_block_outputs = dict(state.block_outputs)
        now = datetime.now(timezone.utc)

        for block_contract in state.spec.blocks:
            if block_contract.kind != "DETERMINISTIC_DATA":
                continue

            block_id = block_contract.id
            if block_id not in updated_blocks:
                continue

            source_kind = block_contract.source_pipeline
            file_ref = _find_artifact_for_pipeline(source_kind, state.spec, state.artifacts_normalized)

            if file_ref is None and not state.artifacts_normalized:
                new_warnings.append(ExtractionWarning(
                    block_id=block_id,
                    message=f"No artifact found for block {block_id!r} (source_pipeline={source_kind!r}).",
                    kind="missing_input",
                ))
                continue

            # PRO.3 — las opciones del bloque viajan al pipeline. Iba `options={}`, así que el
            # código del script aprobado no llegaba nunca y el pipeline respondía
            # `SCRIPT_NOT_APPROVED`: el síntoma acusaba a la aprobación, que estaba bien.
            opciones = dict(getattr(block_contract, "options", {}) or {})

            # FUN.3 — el código ya no viene en el bloque: viene del catálogo. El nodo no sabe de
            # orígenes; le pide «lo ejecutable» al resolutor, que en FUN.5 sabrá además resolver
            # una función empaquetada sin que esto cambie.
            funcion_ref = getattr(block_contract, "funcion_ref", None)
            ejecutable = None
            if funcion_ref is not None:
                try:
                    ejecutable = await self._resolver_funcion(funcion_ref)
                except Exception as exc:  # noqa: BLE001 — el fallo se convierte en aviso del bloque
                    # EN ALTO y con el motivo: una función retirada o suspendida no puede
                    # dejar el bloque vacío en silencio (la lección de los perfiles sin
                    # configurar).
                    new_warnings.append(ExtractionWarning(
                        block_id=block_id, message=str(exc), kind="funcion_no_ejecutable",
                    ))
                    updated_blocks[block_id] = updated_blocks[block_id].model_copy(update={
                        "status": "failed",
                        "failure_kind": "extraction_failed",
                        "last_error_message": str(exc)[:500],
                        "last_updated_by": "system",
                        "updated_at": now,
                    })
                    new_block_outputs[block_id] = {"partial": {}}
                    continue
                if ejecutable.origen != "paquete":
                    opciones.update(ejecutable.como_opciones_del_pipeline())

            de_paquete = ejecutable is not None and ejecutable.origen == "paquete"

            try:
                if de_paquete:
                    # In-process, sin sandbox y con el contrato validado delante. La frontera de
                    # confianza está en quien instala el paquete, y así lo dice FUN.5.
                    result = await self._ejecutar_ejecutable(
                        ejecutable,
                        ficheros=_ficheros_del_bloque(ejecutable, file_ref),
                        parametros=dict(opciones.get("parametros") or {}),
                    )
                else:
                    inp = ExtractionInput(
                        source_kind=cast(Any, source_kind),
                        file_ref=file_ref,
                        options=opciones,
                    )
                    pipeline = self._factory.get(source_kind)
                    result = await _extraer(pipeline, inp)
            except Exception as exc:  # noqa: BLE001 — el fallo se convierte en aviso del bloque
                new_warnings.append(ExtractionWarning(
                    block_id=block_id, message=str(exc), kind="extraction_error",
                ))
                updated_blocks[block_id] = updated_blocks[block_id].model_copy(update={
                    "status": "failed",
                    "failure_kind": "extraction_failed",
                    "last_error_message": str(exc)[:500],
                    "last_updated_by": "system",
                    "updated_at": now,
                })
                new_block_outputs[block_id] = {"partial": {}}
                continue

            content = {
                "tables": [t.model_dump() for t in result.tables],
                "metrics": [m.model_dump() for m in result.metrics],
                "free_text": result.free_text,
                "document": result.document.model_dump() if result.document else None,
            }
            for pw in result.warnings:
                new_warnings.append(ExtractionWarning(
                    block_id=block_id, message=pw.message, kind=pw.code.lower(),
                ))

            block_state = updated_blocks[block_id]
            new_status = "extracted" if block_state.status in ("draft", "missing_input") else block_state.status
            updated_blocks[block_id] = block_state.model_copy(update={
                "content": content,
                "status": new_status,
                "last_updated_by": "system",
                "updated_at": now,
            })

        return {"blocks": updated_blocks, "warnings": new_warnings, "block_outputs": new_block_outputs}


class SlotAmbiguo(ValueError):
    """La función declara varios slots y el bloque trae un fichero: no se adivina cuál."""


def _ficheros_del_bloque(ejecutable: Any, file_ref: Any) -> dict[str, str]:
    """Los ficheros que recibe una función de paquete, con el nombre de slot **que ella declara**.

    El nodo trabaja con **un** fichero por bloque —así está montado desde 9R— mientras el
    contrato de una función habla de slots con nombre. El puente es el contrato de la función,
    que el resolutor ya trae en `contrato_entrada`.

    **Antes miraba el bloque, y por eso no funcionaba nunca (APER.15).** Buscaba
    `block_contract.slot` —un campo que `blocks.py` no tiene— o `options["slot"]`, que ya está
    ocupado: `manual_pipeline` lo usa como **diccionario** y esto exigía `str`. Devolvía `{}`
    siempre, así que una función empaquetada con slot obligatorio fallaba la validación antes de
    ejecutarse: FUN.5 resolvía y enrutaba bien, y la entrada no llegaba.

    Y propagar el slot de la **especificación** no habría servido: `datos_del_script` y `gastos`
    son espacios de nombres distintos y nada los mapea. El que manda es el de la función.

    **Con varios slots se falla, no se adivina.** Poner el fichero en el primero que aparezca
    daría un resultado —el de gastos leído como plantilla— y un resultado equivocado es peor que
    un error: nadie lo revisa. El día que un bloque necesite alimentar dos slots, lo tendrá que
    declarar, y este error es el que lo pedirá.
    """
    if file_ref is None:
        return {}

    contrato = getattr(ejecutable, "contrato_entrada", None) or {}
    declarados = [
        (s.get("slot_id") if isinstance(s, dict) else getattr(s, "slot_id", None))
        for s in (contrato.get("slots") or [])
    ]
    declarados = [s for s in declarados if s]

    if not declarados:
        # Una función que sólo toma parámetros es legítima: no hay dónde poner el fichero.
        return {}
    if len(declarados) > 1:
        raise SlotAmbiguo(
            f"la función declara {len(declarados)} slots ({', '.join(declarados)}) y el bloque "
            "trae un solo fichero, así que no se puede decidir a cuál va. Hace falta que el "
            "bloque declare el destino: adivinarlo daría un resultado con el fichero en el "
            "slot equivocado."
        )

    return {declarados[0]: str(getattr(file_ref, "key", file_ref))}
