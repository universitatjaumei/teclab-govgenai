"""Los enlaces que el asistente ofrece como fundamento, comprobados contra el sitio (issue #14).

Deploy: edge

**Por qué existe.** Cuatro de los enlaces que el asistente daba como fundamento no llevaban a
ninguna parte, y salieron a mano. Una cita sin enlace verificable obliga a creerse al asistente,
que es justo lo que este proyecto no quiere: el fundamento existe para poder contrastarlo. Un
enlace muerto **es peor que no citar**, porque aparenta verificación.

**Dos formas de estar muerto.** Que la página no responda es la obvia. La otra es peor: la página
responde 200 y el **ancla no existe** en ella, así que el lector aterriza en la cabecera del
documento convencido de estar leyendo el artículo citado. Nada falla y la cita miente.

**Esto NO es un gate de CI**, y la razón es la misma que separa `retrieval_metrics` de
`run_golden`: depende de un servidor ajeno y de la red. Un rojo aquí puede significar «el corpus
se está republicando» o «la red del runner va mal», y un gate que falla por causas que no son el
cambio enseña a ignorarlo. Se ejecuta a mano o de noche.

Lo que sí corre en CI es `comprobar_enlaces`, con el acceso HTTP inyectado: la lógica del
veredicto —qué cuenta como muerto— es determinista y se fija con tests.

**No lee ninguna conversación.** La issue encontró los cuatro auditando conversaciones guardadas,
que fue buen método de diagnóstico y no hace falta para la comprobación permanente: los enlaces se
derivan de `hub_documents`. Detectar lo mismo sin tocar datos personales es preferible aunque
cueste igual.

    uv run python -m server.app.modules.agents_hub.evaluation.verificar_enlaces \
        --chatbot-id <uuid> [--limite 0] [--concurrencia 8]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable

from server.app.modules.agents_hub.ingestion.ancores_del_diari import mapa_de_ancores

#: `id="art-9"` o `name="art-9"`, con comillas simples o dobles y espacios alrededor del `=`.
#: Se busca el atributo y no la cadena suelta: `art-9` aparece en el texto de cualquier norma que
#: se cite a sí misma, y buscarla a pelo daría por viva un ancla que no existe.
def _ancla_presente(html: str, ancla: str) -> bool:
    patron = rf"""\b(?:id|name)\s*=\s*['"]{re.escape(ancla)}['"]"""
    return re.search(patron, html) is not None


@dataclass(frozen=True)
class Hallazgo:
    url: str
    #: "no_resuelve" | "ancla_ausente" | "ancla_de_otro_articulo"
    #:
    #: El tercero es de la issue #157 y es **el peor de los tres**: el ancla existe, la página
    #: responde, el enlace se abre… y lleva a otro artículo. No da error y no se ve. Aparece
    #: cuando el mapa que la ingesta leyó del diario ha envejecido: el BOE renumera sus bloques
    #: al reconsolidar una norma reformada.
    motivo: str
    detalle: str


Fetch = Callable[[str], Awaitable[tuple[int, str]]]


async def comprobar_enlaces(
    urls: list[str],
    fetch: Fetch,
    concurrencia: int = 8,
    *,
    articulo_citado: dict[str, str] | None = None,
) -> list[Hallazgo]:
    """Los hallazgos de una lista de URLs de cita. Lista vacía significa que todas viven.

    `fetch` devuelve `(status, cuerpo)`. Se inyecta para que esta función —que es la que decide
    qué cuenta como muerto— sea determinista y pueda correr en CI sin red.

    `articulo_citado` mapea cada URL con fragmento a **la ancora nuestra que se estaba citando**
    (`art-18`). Donde se sabe, se comprueba además la **correspondencia**: que el ancla del
    diario etiquete ese artículo y no otro (issue #157). Donde no se sabe, se comprueba lo de
    siempre —que el ancla exista—, que es lo que mide la #14.

    La comprobación nueva **se suma** a la vieja y no la sustituye: un ancla ausente sigue
    contando como ausente. Un ancla que no existe no puede etiquetar nada, así que no tendría
    sentido preguntarle a cuál.
    """
    # Las anclas del mismo documento comparten descarga. El corpus tiene cientos de fragmentos
    # por norma: pedir la página una vez por fragmento convertiría la comprobación en algo
    # parecido a un ataque contra el propio sitio.
    por_pagina: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        pagina, _, ancla = url.partition("#")
        por_pagina[pagina].append(ancla)

    # `Semaphore(0)` no es «sin límite»: deja todas las tareas esperando para siempre, y el
    # medidor se cuelga sin decir por qué. Un cero llega solo desde `--concurrencia 0`, que es
    # justo lo que alguien escribiría creyendo que significa «sin tope».
    if concurrencia < 1:
        raise ValueError(
            f"concurrencia={concurrencia}: tiene que ser al menos 1. Un cero no quita el límite, "
            f"deja la comprobación colgada indefinidamente."
        )

    limite = asyncio.Semaphore(concurrencia)
    hallazgos: list[Hallazgo] = []

    async def _una(pagina: str, anclas: list[str]) -> list[Hallazgo]:
        async with limite:
            try:
                status, cuerpo = await fetch(pagina)
            except Exception as exc:  # noqa: BLE001
                # Una excepción NO es «está viva». Sin este `except`, un fallo de red dejaría
                # la comprobación en silencio y el informe diría que todo está bien.
                return [Hallazgo(pagina, "no_resuelve", f"{type(exc).__name__}: {exc}")]

        if status != 200:
            return [Hallazgo(pagina, "no_resuelve", str(status))]

        hallazgos_de_la_pagina: list[Hallazgo] = []
        # El mapa se construye **una vez por página** y sólo si alguna de sus citas declara
        # artículo: parsear un texto consolidado de dos megas por cada ancla sería tan caro como
        # volver a descargarlo.
        mapa: dict[str, str] | None = None

        for a in dict.fromkeys(a for a in anclas if a):
            url = f"{pagina}#{a}"
            if not _ancla_presente(cuerpo, a):
                hallazgos_de_la_pagina.append(
                    Hallazgo(url, "ancla_ausente", f"la pagina no declara `{a}`")
                )
                continue

            citado = (articulo_citado or {}).get(url)
            if not citado:
                continue
            if mapa is None:
                mapa = mapa_de_ancores(cuerpo)
            # Un mapa vacío significa que de esta página no se sabe leer artículos —no es del
            # BOE, o cambió el marcado—, y de ahí no se puede concluir que la cita esté mal.
            if not mapa:
                continue

            deberia = mapa.get(citado)
            if deberia is not None and deberia != a:
                etiqueta = next(
                    (nuestra for nuestra, suya in mapa.items() if suya == a), "?"
                )
                hallazgos_de_la_pagina.append(
                    Hallazgo(
                        url,
                        "ancla_de_otro_articulo",
                        f"`{a}` etiqueta `{etiqueta}` y la cita dice `{citado}`, "
                        f"que hoy es `{deberia}`",
                    )
                )

        return hallazgos_de_la_pagina

    for lote in await asyncio.gather(
        *(_una(p, a) for p, a in por_pagina.items())
    ):
        hallazgos.extend(lote)
    return hallazgos


def comprobar_que_mide_lo_desplegado(base: str | None, sin_sitio_publicado: bool) -> None:
    """Se niega a medir si falta `CORPUS_SITE_BASE_URL` y nadie ha dicho que falte a propósito.

    **Pasó el 2026-09-25 y el resultado engañó.** El detector se ejecutó en un contenedor de un
    solo uso al que se le pasaba `/opt/govgenai/.env.runtime`, y esa variable **no está ahí**:
    vive en el bloque `environment:` del compose. Sin ella, `url_de_cita` se salta la rama del
    sitio publicado y compone la URL del PDF del portal.

    O sea que midió **un sistema que no existe**, y no lo dijo. Dio 292 URL con 2 fallos, que es
    un resultado pequeño y creíble; lo real eran **7.696 URL con 0 fallos**. De paso dejó sin
    comprobar las miles de anclas de nuestro sitio, que son justamente las que el informe
    afirmaba estar bien.

    Un medidor mal configurado no da error: da una cifra más cómoda. Por eso esto **falla** en vez
    de avisar — un aviso por la salida de error se pierde entre el resto.

    **Y no es un cerrojo**: un despliegue sin sitio publicado es una configuración soportada —el
    propio `citations.py` dice que vacía significa desactivado—. Para ése está la bandera, que
    convierte el hueco en una declaración.
    """
    if base and base.strip():
        return
    if sin_sitio_publicado:
        print(
            "AVISO: sin sitio publicado; las normas propias se comprobaran contra su PDF.",
            file=sys.stderr,
        )
        return
    raise SystemExit(
        "CORPUS_SITE_BASE_URL no esta definida, asi que las normas propias se citarian contra "
        "el PDF del portal y no contra el sitio publicado: se estaria midiendo un sistema "
        "distinto del que hay desplegado.\n\n"
        "Ojo: en la VM esa variable NO esta en `/opt/govgenai/.env.runtime`, esta en el bloque "
        "`environment:` del compose. Para un contenedor de un solo uso hay que pasarla a mano:\n"
        "    -e CORPUS_SITE_BASE_URL=$(docker exec govgenai_app printenv CORPUS_SITE_BASE_URL)\n\n"
        "Si el despliegue de verdad no publica sitio, dilo con `--sin-sitio-publicado`."
    )


async def _fetch_real(timeout: float = 15.0) -> Fetch:
    """El acceso HTTP de verdad. `httpx` se importa aquí y no arriba: la lógica del veredicto
    corre en CI y no tiene por qué arrastrar la red."""
    import httpx

    cliente = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def fetch(url: str) -> tuple[int, str]:
        respuesta = await cliente.get(url)
        return respuesta.status_code, respuesta.text

    return fetch


async def _run(args: argparse.Namespace) -> int:
    import os

    from sqlalchemy import select

    # Lo primero, antes de tocar la base: si esto midiera otra configuracion, el resto sobra.
    comprobar_que_mide_lo_desplegado(
        os.getenv("CORPUS_SITE_BASE_URL"), args.sin_sitio_publicado
    )

    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )
    from server.app.modules.agents_hub.database.operational_models import (
        HubDocument,
        HubDocumentChunk,
    )
    from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita

    engine = create_async_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            # **Sólo SELECT.** Esta herramienta no escribe nada, y se ejecuta contra la base que
            # sirve a gente de verdad.
            #
            # Y se comprueba lo que el lector ve, que no es lo mismo que lo que hay guardado:
            # `chunk.source_url` es la URL de **ingesta**, mientras que la cita se compone al
            # recuperar con `url_de_cita(documento, metadata)` —es lo que hace
            # `vector_strategy`—. Comprobar la de ingesta daría un informe sobre unas URL que
            # nadie llega a pinchar.
            #
            # **Dos consultas, y la pesada devuelve columnas planas.** Hubo dos intentos peores
            # antes de éste, y los dos merecen quedar escritos porque el segundo parecía el
            # arreglo del primero:
            #
            #  1. `.all()` sobre la unión completa de documentos y fragmentos. Cientos de miles
            #     de filas de objetos ORM de golpe: es la consulta que el 2026-09-24 se comió la
            #     memoria de la VM y dejó el sitio caído 50 minutos.
            #  2. La misma unión con `stream()`, que parecía resolverlo. **No lo resolvía**: las
            #     filas llegan de una en una, pero cada una construye un objeto ORM que la sesión
            #     retiene en su mapa de identidad, así que la memoria crece igual. Murió por OOM
            #     contra el corpus real, dentro de un contenedor con 256 MB — que es donde tenía
            #     que morir.
            #
            # Lo que sí funciona es no pedir objetos. Los documentos son unos cientos y caben;
            # los fragmentos son cientos de miles, pero de ellos sólo hace falta el par
            # `(documento, ancla)` **distinto**, que son unos pocos miles de tuplas planas.
            documentos = {
                d.id: d
                for d in (
                    await session.execute(
                        select(HubDocument).where(HubDocument.chatbot_id == args.chatbot_id)
                    )
                )
                .scalars()
                .all()
            }

            ancora = HubDocumentChunk.chunk_metadata["ancora"].astext
            pares = (
                await session.execute(
                    select(HubDocumentChunk.document_id, ancora)
                    .where(HubDocumentChunk.document_id.in_(documentos))
                    .distinct()
                )
            ).all()

            vistas: set[str] = set()
            # Issue #157 — qué artículo decía la cita que estaba citando, por URL. Es lo que
            # convierte «el ancla existe» en «el ancla etiqueta lo que la cita dice». Sólo se
            # apunta cuando la URL sale con fragmento: sin fragmento no hay nada que comprobar.
            citado_en: dict[str, str] = {}
            for doc_id, anc in pares:
                documento = documentos.get(doc_id)
                if documento is None:
                    continue
                u = url_de_cita(documento, {"ancora": anc} if anc else {})
                if u:
                    vistas.add(u)
                    if anc and "#" in u:
                        citado_en[u] = anc
            urls = sorted(vistas)
            print(
                f"{len(documentos)} documentos · {len(pares)} pares documento/ancla",
                file=sys.stderr,
            )
    finally:
        await engine.dispose()

    if args.limite:
        urls = urls[: args.limite]

    print(f"{len(urls)} URL de cita distintas", file=sys.stderr)
    fetch = await _fetch_real()
    hallazgos = await comprobar_enlaces(
        urls, fetch, args.concurrencia, articulo_citado=citado_en
    )

    for h in sorted(hallazgos, key=lambda x: (x.motivo, x.url)):
        print(f"{h.motivo}\t{h.url}\t{h.detalle}")

    print(
        f"{len(hallazgos)} enlaces con problema de {len(urls)} comprobados",
        file=sys.stderr,
    )
    return 1 if hallazgos else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chatbot-id", required=True, type=uuid.UUID, dest="chatbot_id")
    parser.add_argument("--limite", type=int, default=0, help="0 = sin limite")
    parser.add_argument("--concurrencia", type=int, default=8)
    parser.add_argument(
        "--sin-sitio-publicado",
        action="store_true",
        dest="sin_sitio_publicado",
        help="el despliegue no publica sitio de corpus; las normas propias se citan por su PDF",
    )
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
