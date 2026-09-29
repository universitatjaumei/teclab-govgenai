"""Issue #157 — el ancla de un artículo del BOE se lee de la página, no se calcula.

**De dónde viene.** La #152 retiró la composición de anclas porque **no se puede calcular**: el
diario usa dos esquemas y sólo coinciden en los artículos de un dígito.

    Ley Orgánica 6/2001   #a110   → Artículo 110    (el ancla ES el número)
    Ley 9/2017 Contratos  #a1-10  → Artículo 18     (contador de bloques del BOE)

No hay aritmética que lleve de 18 a `1-10`: depende de cuántos bloques —preámbulo, títulos,
capítulos— van delante. Desde entonces una cita a la Ley de Contratos lleva a la cabecera de la
ley y no al artículo. Esto recupera la precisión leyendo la página **una vez, en la ingesta**, en
vez de en cada respuesta.

**Y por eso se guarda el mapa y no el esquema.** Clasificar el esquema era la propuesta inicial y
es más barato, pero para uno de los dos no existe fórmula, así que habría que leer la página
igual. Leída la página, construir el mapa completo no cuesta casi nada más y es estrictamente
mejor: vale para los dos esquemas sin distinguirlos, no hay catálogo de esquemas que mantener, y
**acierta donde la fórmula fallaba por otra razón** — el `#a114` de la Ley Orgánica 6/2001 no
existe porque ese artículo está derogado, y un mapa leído de la página sencillamente no lo trae.

El marcado del que se lee, comprobado contra las páginas reales el 2026-09-28:

    <div class="bloque" id="a1-10">
      <p class="bloque">[Bloque 26: #a1-10]</p>
      <h5 class="articulo">Artículo 18. Contratos mixtos.</h5>

**Qué entra en el mapa y qué no.** Sólo artículos. Las disposiciones, los anexos y las secciones
del corpus (`da-N`, `df-N`, `annex-N`, `sec-N`) **nunca han tenido fragmento** en una cita al
diario: la regla retirada sólo componía ancla cuando el nuestra era `art-N`, así que las 785 rotas
eran todas de artículo. Añadirlas es ampliar, no arreglar, y exige traducir ordinales en letra
—«disposición adicional séptima»— que es una lista escrita a mano de las que este módulo ya ha
visto quedarse corta tres veces. Se deja fuera a propósito y se dice.
"""

from __future__ import annotations

import pytest

from server.app.modules.agents_hub.ingestion.ancores_del_diari import (
    CLAVE,
    mapa_de_ancores,
    refrescar_ancores,
)

_URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902"
_OTRA = "https://www.boe.es/buscar/act.php?id=BOE-A-2001-19995"

#: El esquema de contador de bloques, tal como lo sirve la Ley 9/2017.
_CONTRATOS = """
<div class="bloque" id="a1">
  <p class="bloque">[Bloque 9: #a1]</p>
  <h5 class="articulo">Artículo 1. Objeto y finalidad.</h5>
  <p class="parrafo">La presente Ley tiene por objeto…</p>
</div>
<div class="bloque" id="a1-10">
  <p class="bloque">[Bloque 26: #a1-10]</p>
  <h5 class="articulo">Artículo 18. Contratos mixtos.</h5>
  <p class="parrafo">1. Se entenderá por contrato mixto…</p>
</div>
<div class="bloque" id="a3-59">
  <p class="bloque">[Bloque 400: #a3-59]</p>
  <h5 class="articulo">Artículo 347. Plataforma de Contratación.</h5>
</div>
"""

#: El esquema en que el ancla es el número, tal como lo sirve la Ley Orgánica 6/2001.
_UNIVERSIDADES = """
<div class="bloque" id="a110">
  <p class="bloque">[Bloque 120: #a110]</p>
  <h5 class="articulo">Artículo 110. De la movilidad.</h5>
</div>
<div class="bloque" id="a118">
  <p class="bloque">[Bloque 128: #a118]</p>
  <h5 class="articulo">Artículo 118. Del régimen económico.</h5>
</div>
"""


class TestElMapaSaleDeLaPagina:

    def test_traduce_el_contador_de_bloques(self):
        """El caso que abrió la issue: del artículo 18 al ancla `a1-10`."""
        assert mapa_de_ancores(_CONTRATOS)["art-18"] == "a1-10"

    def test_y_tambien_el_esquema_en_que_el_ancla_es_el_numero(self):
        """Un solo camino para los dos esquemas: no se clasifica, se lee."""
        assert mapa_de_ancores(_UNIVERSIDADES)["art-110"] == "a110"

    def test_recoge_todos_los_articulos_de_la_pagina(self):
        assert mapa_de_ancores(_CONTRATOS) == {
            "art-1": "a1",
            "art-18": "a1-10",
            "art-347": "a3-59",
        }

    def test_un_articulo_derogado_no_esta_en_el_mapa(self):
        """Es la ventaja que la fórmula no podía tener.

        El texto consolidado no renderiza un artículo derogado, así que su bloque no existe y el
        mapa no lo trae. La cita se queda sin fragmento —el comportamiento de hoy— en vez de
        apuntar a un ancla inventada.
        """
        mapa = mapa_de_ancores(_UNIVERSIDADES)

        assert "art-114" not in mapa
        assert "art-118" in mapa


class TestLoQueNoEsUnArticulo:

    def test_las_disposiciones_se_quedan_fuera_a_proposito(self):
        """Nunca tuvieron fragmento, así que dejarlas fuera no quita nada.

        Traducirlas exigiría convertir «séptima» en `7`, que es una lista escrita a mano. Se
        amplía el día que alguien lo necesite, y entonces con su medición delante.
        """
        html = """
        <div class="bloque" id="a4-1">
          <h5 class="articulo">Disposición adicional séptima. Bienes del Patrimonio.</h5>
        </div>
        """
        assert mapa_de_ancores(html) == {}

    def test_un_bloque_sin_encabezado_no_entra(self):
        html = '<div class="bloque" id="preambulo"><p class="parrafo">Texto.</p></div>'

        assert mapa_de_ancores(html) == {}

    def test_el_encabezado_va_con_su_bloque_y_no_con_el_siguiente(self):
        """Sin esto el mapa se desplaza entero y cada cita lleva al artículo de al lado.

        Es el modo de fallo que la issue llama peor que el de partida: un ancla que **sí existe**
        y etiqueta otro artículo no da error y no se ve.
        """
        mapa = mapa_de_ancores(_CONTRATOS)

        assert mapa["art-1"] == "a1"
        assert mapa["art-1"] != "a1-10"


class TestLasVariantesDelArticulado:

    def test_bis_ter_y_los_demas(self):
        """El corpus tiene 19 `art-N-bis`, 5 `ter`, 4 `quater`, 3 `quinquies` y 2 `sexies`."""
        html = """
        <div class="bloque" id="a2-5">
          <h5 class="articulo">Artículo 30 bis. Encargos a medios propios.</h5>
        </div>
        <div class="bloque" id="a2-6">
          <h5 class="articulo">Artículo 30 ter. Otro más.</h5>
        </div>
        """
        mapa = mapa_de_ancores(html)

        assert mapa["art-30-bis"] == "a2-5"
        assert mapa["art-30-ter"] == "a2-6"

    def test_no_confunde_el_articulo_30_con_el_30_bis(self):
        """Sin esto uno pisa al otro en el diccionario y una de las dos citas miente."""
        html = """
        <div class="bloque" id="a30">
          <h5 class="articulo">Artículo 30. El de siempre.</h5>
        </div>
        <div class="bloque" id="a30-bis">
          <h5 class="articulo">Artículo 30 bis. El añadido.</h5>
        </div>
        """
        mapa = mapa_de_ancores(html)

        assert mapa["art-30"] == "a30"
        assert mapa["art-30-bis"] == "a30-bis"


class TestCuandoLaPaginaNoSirve:

    def test_una_pagina_vacia_da_un_mapa_vacio_y_no_una_excepcion(self):
        """Quien llama decide qué hacer sin mapa; reventar aquí pararía la ingesta entera."""
        assert mapa_de_ancores("") == {}

    def test_html_que_no_es_del_boe_da_un_mapa_vacio(self):
        assert mapa_de_ancores("<html><body><h1>Otra cosa</h1></body></html>") == {}


class TestElRefrescoGuardaElMapa:
    """La segunda mitad: leer la página una vez y dejar el mapa con el documento."""

    def _documento(self, url: str, metadatos: dict | None = None):
        from types import SimpleNamespace

        return SimpleNamespace(
            doc_metadata={"url_oficial": url, **(metadatos or {})},
            canonical_url=None,
        )

    def _fetch(self, respuestas: dict):
        async def fetch(url: str):
            valor = respuestas[url]
            if isinstance(valor, Exception):
                raise valor
            return valor

        return fetch

    @pytest.mark.asyncio
    async def test_deja_el_mapa_en_los_metadatos(self):
        doc = self._documento(_URL)
        refresco = await refrescar_ancores([doc], self._fetch({_URL: (200, _CONTRATOS)}))

        assert doc.doc_metadata[CLAVE]["art-18"] == "a1-10"
        assert refresco.actualizadas == 1

    @pytest.mark.asyncio
    async def test_una_descarga_por_pagina_y_no_por_documento(self):
        """El corpus tiene una versión por lengua: son cuatro documentos por norma."""
        pedidas = []

        async def fetch(url: str):
            pedidas.append(url)
            return 200, _CONTRATOS

        cuatro = [self._documento(_URL) for _ in range(4)]
        await refrescar_ancores(cuatro, fetch)

        assert pedidas == [_URL]
        assert all(d.doc_metadata[CLAVE]["art-18"] == "a1-10" for d in cuatro)

    @pytest.mark.asyncio
    async def test_que_el_diario_no_responda_no_rompe_la_ingesta(self):
        """La norma entra igual y sus citas van sin fragmento, como antes de esto."""
        doc = self._documento(_URL)
        refresco = await refrescar_ancores(
            [doc], self._fetch({_URL: ConnectionError("el BOE no contesta")})
        )

        assert CLAVE not in doc.doc_metadata
        assert refresco.actualizadas == 0
        assert _URL in refresco.no_se_pudo

    @pytest.mark.asyncio
    async def test_un_mapa_vacio_no_pisa_uno_bueno(self):
        """Cambió el marcado, o llegó una página de error con estado 200.

        Sustituir el mapa por `{}` apagaría en silencio todas las citas de esa norma, que es
        peor que quedarse con uno viejo y que el detector de correspondencia lo cace.
        """
        doc = self._documento(_URL, {CLAVE: {"art-18": "a1-10"}})
        refresco = await refrescar_ancores(
            [doc], self._fetch({_URL: (200, "<html>otra cosa</html>")})
        )

        assert doc.doc_metadata[CLAVE] == {"art-18": "a1-10"}
        assert refresco.sin_articulos == [_URL]

    @pytest.mark.asyncio
    async def test_no_pude_mirar_y_mire_y_no_hay_nada_se_cuentan_aparte(self):
        """Confundirlos es como un medidor informa de cero en verde."""
        refresco = await refrescar_ancores(
            [self._documento(_URL), self._documento(_OTRA)],
            self._fetch({_URL: (500, ""), _OTRA: (200, "<html></html>")}),
        )

        assert list(refresco.no_se_pudo) == [_URL]
        assert refresco.sin_articulos == [_OTRA]

    @pytest.mark.asyncio
    async def test_el_dogv_no_se_toca(self):
        """Usa otro marcado. Sus citas van sin fragmento, igual que antes, y no inventadas."""
        doc = self._documento("https://dogv.gva.es/es/resultat-dogv?signatura=2025/19882")

        refresco = await refrescar_ancores([doc], self._fetch({}))

        assert CLAVE not in doc.doc_metadata
        assert refresco.actualizadas == 0

    @pytest.mark.asyncio
    async def test_volver_a_pasar_sin_cambios_no_reescribe(self):
        """La ingesta es incremental: una pasada que no cambia nada no debe ensuciar filas."""
        doc = self._documento(_URL)
        await refrescar_ancores([doc], self._fetch({_URL: (200, _CONTRATOS)}))
        segundo = await refrescar_ancores([doc], self._fetch({_URL: (200, _CONTRATOS)}))

        assert segundo.actualizadas == 0
        assert segundo.sin_cambio == 1


class TestLaCitaUsaElMapa:
    """La mitad que se ve: el enlace lleva al artículo, no a la cabecera de la ley."""

    def _externa(self, **extra):
        from types import SimpleNamespace

        metadatos = {"tipus_document": "norma_externa", "url_oficial": _URL, **extra}
        return SimpleNamespace(canonical_url=_URL, doc_metadata=metadatos)

    def test_el_enlace_lleva_al_articulo(self):
        from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita

        documento = self._externa(**{CLAVE: {"art-18": "a1-10"}})

        assert url_de_cita(documento, {"ancora": "art-18"}) == f"{_URL}#a1-10"

    def test_un_articulo_que_no_esta_en_el_mapa_se_cita_sin_fragmento(self):
        """El comportamiento de hoy, y el bueno: la cabecera del documento correcto es mejor
        que un punto equivocado del documento correcto."""
        from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita

        documento = self._externa(**{CLAVE: {"art-18": "a1-10"}})

        assert url_de_cita(documento, {"ancora": "art-114"}) == _URL

    def test_sin_mapa_se_cita_sin_fragmento(self):
        """Una norma cuya página no se ha podido leer nunca, o de un diario que no se lee."""
        from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita

        assert url_de_cita(self._externa(), {"ancora": "art-18"}) == _URL

    def test_nuestra_ancora_no_se_pega_nunca_tal_cual(self):
        """Es la regla de la #152: un ancla inventada lleva a un punto que no existe sin que
        se note. El mapa es la única fuente, y si no la trae, no hay fragmento."""
        from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita

        for metadata in ({"ancora": "art-18"}, {"ancora": "da-7"}, {"ancora": "annex-1"}):
            assert "#" not in (url_de_cita(self._externa(), metadata) or "")

    def test_una_disposicion_sigue_sin_fragmento_aunque_haya_mapa(self):
        """El mapa sólo trae artículos, y eso se nota aquí sin ninguna regla de más."""
        from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita

        documento = self._externa(**{CLAVE: {"art-18": "a1-10"}})

        assert url_de_cita(documento, {"ancora": "da-7"}) == _URL


class TestElDetectorComprubaCorrespondencia:
    """La parte que la issue marca como **no opcional ni posterior**.

    Sin ella, esto cambia un fallo visible por uno invisible. El de partida era un ancla que **no
    existe**: el navegador la ignora y el lector aterriza en la cabecera. Un mapa envejecido
    —el BOE renumera sus bloques al reconsolidar una norma reformada— produce un ancla que **sí
    existe y lleva a otro artículo**, y eso no se ve, no da error, y en un asistente normativo es
    exactamente lo que el proyecto no puede permitirse.

    El detector de enlaces de la #14 no lo cazaría: comprueba que el ancla exista, no que
    etiquete el artículo que la cita dice.
    """

    def _fetch_de(self, respuestas):
        async def fetch(url: str):
            return respuestas.get(url, (599, ""))

        return fetch

    @pytest.mark.asyncio
    async def test_un_ancla_que_etiqueta_otro_articulo_es_un_hallazgo(self):
        from server.app.modules.agents_hub.evaluation.verificar_enlaces import (
            comprobar_enlaces,
        )

        fetch = self._fetch_de({_URL: (200, _CONTRATOS)})

        hallazgos = await comprobar_enlaces(
            [f"{_URL}#a1-10"], fetch, articulo_citado={f"{_URL}#a1-10": "art-347"}
        )

        assert [h.motivo for h in hallazgos] == ["ancla_de_otro_articulo"]
        assert "art-18" in hallazgos[0].detalle

    @pytest.mark.asyncio
    async def test_el_ancla_correcta_no_da_hallazgo(self):
        """Sin esto, lo de arriba se cumpliría marcando todas las citas como equivocadas."""
        from server.app.modules.agents_hub.evaluation.verificar_enlaces import (
            comprobar_enlaces,
        )

        fetch = self._fetch_de({_URL: (200, _CONTRATOS)})

        hallazgos = await comprobar_enlaces(
            [f"{_URL}#a1-10"], fetch, articulo_citado={f"{_URL}#a1-10": "art-18"}
        )

        assert hallazgos == []

    @pytest.mark.asyncio
    async def test_sin_saber_que_articulo_se_citaba_solo_se_comprueba_existencia(self):
        """El comportamiento de la #14, intacto: una URL sin artículo declarado se mide igual."""
        from server.app.modules.agents_hub.evaluation.verificar_enlaces import (
            comprobar_enlaces,
        )

        fetch = self._fetch_de({_URL: (200, _CONTRATOS)})

        assert await comprobar_enlaces([f"{_URL}#a1-10"], fetch) == []

    @pytest.mark.asyncio
    async def test_un_ancla_ausente_sigue_contando_como_ausente(self):
        """La comprobación nueva se suma a la vieja; no la sustituye ni la tapa."""
        from server.app.modules.agents_hub.evaluation.verificar_enlaces import (
            comprobar_enlaces,
        )

        fetch = self._fetch_de({_URL: (200, _CONTRATOS)})

        hallazgos = await comprobar_enlaces(
            [f"{_URL}#a9-99"], fetch, articulo_citado={f"{_URL}#a9-99": "art-18"}
        )

        assert [h.motivo for h in hallazgos] == ["ancla_ausente"]


class TestSoloSePideAlDiarioDeVerdad:
    """Hallazgo de la revisión de la PR #189: la URL viene del corpus y nadie validaba su host.

    `url_oficial` llega del front-matter de un `.md` y se descargaba con
    `"boe.es" in url`, que es una subcadena y no un nombre. Con eso pasaban
    `https://boe.es.attacker.example/` y `http://169.254.169.254/latest/boe.es`, y la pasada de
    ingesta los habría pedido — convirtiendo el refresco de anclas en un lector del servidor de
    metadatos de la nube.

    Son dos comprobaciones distintas y las dos hacen falta: **la forma** —que el host sea el
    diario— aquí, y **el destino resuelto** justo antes de pedir la página, con
    `assert_destino_publico`, que es el invariante I15 y se aplica en cada salto porque un
    nombre puede resolver a otra cosa en la petición siguiente.
    """

    def _documento(self, url: str):
        from types import SimpleNamespace

        return SimpleNamespace(doc_metadata={"url_oficial": url}, canonical_url=None)

    @pytest.mark.parametrize(
        "url",
        [
            "https://boe.es.attacker.example/act.php?id=x",
            "http://169.254.169.254/latest/boe.es",
            "https://noboe.es/act.php",
            "https://example.test/?ref=boe.es",
        ],
    )
    def test_un_host_que_solo_contiene_el_nombre_no_cuela(self, url):
        from server.app.modules.agents_hub.ingestion.ancores_del_diari import (
            url_del_diari,
        )

        assert url_del_diari(self._documento(url)) is None

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902",
            "https://boe.es/eli/es/l/2017/11/08/9",
            "https://BOE.ES/buscar/act.php?id=x",
        ],
    )
    def test_el_diario_de_verdad_si(self, url):
        """Sin esto, lo de arriba se cumpliría dejando fuera al BOE entero."""
        from server.app.modules.agents_hub.ingestion.ancores_del_diari import (
            url_del_diari,
        )

        assert url_del_diari(self._documento(url)) is not None

    @pytest.mark.asyncio
    async def test_no_se_descarga_una_direccion_privada(self):
        """I15 — y **se comprueba en cada salto**, no una vez al validar la forma.

        Un host del diario que resolviera a una dirección privada es el patrón del rebinding, y
        aquí se descarta antes de pedir nada.
        """
        from server.app.modules.agents_hub.ingestion.ancores_del_diari import (
            refrescar_ancores,
        )

        pedidas = []

        async def fetch(url: str):
            pedidas.append(url)
            return 200, _CONTRATOS

        from types import SimpleNamespace

        doc = SimpleNamespace(
            doc_metadata={"url_oficial": "https://boe.es/x"}, canonical_url=None
        )

        async def _privado(url, **kwargs):
            from server.app.core.red_publica import DestinoNoPublico

            raise DestinoNoPublico("resuelve a una direccion privada")

        import server.app.modules.agents_hub.ingestion.ancores_del_diari as modulo

        original = modulo.assert_destino_publico
        modulo.assert_destino_publico = _privado
        try:
            refresco = await refrescar_ancores([doc], fetch)
        finally:
            modulo.assert_destino_publico = original

        assert pedidas == [], "se pidio la pagina antes de comprobar el destino"
        assert refresco.no_se_pudo, "y ademas se callo, que es peor"


class TestElMapaEnvejecidoCuyoArticuloYaNoExiste:
    """El caso peor, y el que la primera versión del detector se saltaba.

    Se preguntaba `mapa.get(citado)`: si el artículo citado **ya no está en la página** —lo
    derogaron y el texto consolidado dejó de renderizarlo— la respuesta es `None` y no se decía
    nada. Pero su ancla vieja puede seguir existiendo y etiquetar hoy **otro artículo**, que es
    exactamente el fallo invisible que esta issue venía a impedir.

    Lo señaló la revisión de la PR #189. Se mira por el ancla y no por el artículo: la búsqueda
    inversa lo demuestra sin depender de que el citado siga vivo.
    """

    def _fetch_de(self, respuestas):
        async def fetch(url: str):
            return respuestas.get(url, (599, ""))

        return fetch

    @pytest.mark.asyncio
    async def test_el_ancla_de_un_articulo_derogado_que_hoy_etiqueta_otro(self):
        from server.app.modules.agents_hub.evaluation.verificar_enlaces import (
            comprobar_enlaces,
        )

        # `a1-10` existe y hoy etiqueta el artículo 18. La cita dice `art-114`, que la página
        # ya no trae: el mapa que la ingestó era de antes de la reforma.
        hallazgos = await comprobar_enlaces(
            [f"{_URL}#a1-10"],
            self._fetch_de({_URL: (200, _CONTRATOS)}),
            articulo_citado={f"{_URL}#a1-10": "art-114"},
        )

        assert [h.motivo for h in hallazgos] == ["ancla_de_otro_articulo"]
        assert "art-18" in hallazgos[0].detalle
        assert "no está en la página" in hallazgos[0].detalle

    @pytest.mark.asyncio
    async def test_el_ancla_correcta_sigue_sin_dar_hallazgo(self):
        """Sin esto, lo de arriba se cumpliría marcando todas las citas como equivocadas."""
        from server.app.modules.agents_hub.evaluation.verificar_enlaces import (
            comprobar_enlaces,
        )

        hallazgos = await comprobar_enlaces(
            [f"{_URL}#a1-10"],
            self._fetch_de({_URL: (200, _CONTRATOS)}),
            articulo_citado={f"{_URL}#a1-10": "art-18"},
        )

        assert hallazgos == []
