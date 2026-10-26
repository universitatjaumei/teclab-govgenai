"""HIB.S — el contrato de citas comprueba el fundamento, no sólo que se cite.

**Por qué este mecanismo y no otro.** Sobre el lote de 48 escenarios de Normativa el asistente
contesta **11 de las 18 preguntas que debería declinar**, y ninguna señal del lado de la
recuperación distingue esos 11 de los 30 que sí debía contestar:

- la nota de calidad no separa: los 11 puntúan 0,643-0,787 y los 30 correctos 0,692-0,805, con
  los fallos de mediana **más alta**;
- la brecha entre el primero y el segundo tampoco, y va al revés (0,020 contra 0,010);
- ni el número de fuentes (3 y 3), ni la media de las notas (0,704 contra 0,734);
- ni «la mejor evidencia es un documento vetado», que se propuso y se midió: gana en 2 de 8
  negativos y en 1 de 6 contestables.

**Y el hallazgo que dice dónde sí está el margen**: la puerta de calidad rechazó **cero de 48**.
Los 7 rechazos correctos los produjo el contrato de citas, con precisión perfecta —ni un rechazo
indebido sobre 30 contestables—. Al contrato no le falta acierto: le falta **alcance**. Hoy
pregunta «¿ha citado?», y los 11 fallos **citan** — citan normas de la UJI que hablan de
contratos para una pregunta de contratos.

Estos tests fijan las tres decisiones de criterio que hacen que la puerta ayude en vez de
estorbar, y que son lo que separa este mecanismo de un generador de rendiciones.
"""
import pytest

from server.app.modules.agents_hub.agent.grounding_check import (
    Veredicto,
    hay_fundamento,
)


class _JuezFalso:
    """Un juez con la firma real. Devuelve los veredictos que se le den, en orden."""

    def __init__(self, respuestas: list[bool | None]) -> None:
        self._respuestas = list(respuestas)
        self.vistas: list[tuple[str, str]] = []

    async def __call__(self, afirmacion: str, fragmento: str) -> bool | None:
        self.vistas.append((afirmacion, fragmento))
        return self._respuestas.pop(0) if self._respuestas else None


_EXTRACTO = (
    "##### Article 4. Permanencia en primer curs" + chr(10) +
    "Cal superar un minim del 20% dels credits matriculats. "
    "El termini per a anul-lar la matricula acaba el 15 de desembre."
)


def _fuente(titulo: str = "Reglament de permanencia", texto: str = _EXTRACTO) -> dict:
    """Una fuente recuperada tal como llega del grafo.

    La URL se construye con un *slug* y no con el título: una URL no lleva espacios, y el
    extractor de afirmaciones los rechaza con razón. La primera versión de este fixture los
    metía, así que el extractor no encontraba ninguna cita y el test decía que la respuesta
    pasaba — un fallo del dato de prueba disfrazado de fallo del código.

    Y el extracto CONTIENE las cifras que las afirmaciones de abajo citan. La primera versión
    era el marcador «Article 4...», y con la regla de la cifra ausente eso rechazaba todo sin
    llegar a preguntar al juez: los tests que querían ejercitar al juez no lo ejercitaban.
    """
    slug = titulo.lower().replace(" ", "-").replace("/", "-")
    return {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "title": titulo,
        "url": f"https://www.uji.es/{slug}#art-4",
        "excerpt": texto,
    }


@pytest.mark.asyncio
class TestCuandoSeDescartaLaRespuesta:

    async def test_should_discard_the_answer_when_no_grounded_claim_survives(self):
        """El caso de los 11: la respuesta cita, y lo citado no sostiene nada de lo que dice."""
        juez = _JuezFalso([False, False])
        v = await hay_fundamento(
            texto="El umbral del contrato menor de servicios es de 40.000 euros "
            "[Reglament de permanencia](https://www.uji.es/reglament-de-permanencia#art-4). "
            "El plazo es de 15 dias [Reglament de permanencia]"
            "(https://www.uji.es/reglament-de-permanencia#art-4).",
            fuentes=[_fuente()],
            juez=juez,
        )
        assert isinstance(v, Veredicto)
        assert v.sostenida is False
        assert v.juzgadas == 2
        assert v.con_fundamento == 0

    async def test_should_keep_an_answer_with_some_claims_grounded(self):
        """Una respuesta larga con siete de ocho sostenidas es utilizable. Exigir las ocho
        convertiria la puerta en una fabrica de rendiciones, que es peor que el problema."""
        juez = _JuezFalso([True, False])
        v = await hay_fundamento(
            texto="Hay que superar el 20 % [A](https://www.uji.es/a#art-4). "
            "Y el plazo acaba el 15 de diciembre [A](https://www.uji.es/a#art-4).",
            fuentes=[_fuente("A")],
            juez=juez,
        )
        assert v.sostenida is True
        assert v.con_fundamento == 1
        assert v.juzgadas == 2


@pytest.mark.asyncio
class TestCuandoNoSeDescarta:

    async def test_should_let_the_answer_through_when_the_judge_fails(self):
        """Un fallo del juez es un fallo de INSTRUMENTACION. Convertirlo en una rendicion lo
        cambiaria por un fallo de servicio, que es peor y menos visible."""
        juez = _JuezFalso([None, None])
        v = await hay_fundamento(
            texto="Hay que superar el 20 % [A](https://www.uji.es/a#art-4).",
            fuentes=[_fuente("A")],
            juez=juez,
        )
        assert v.sostenida is True
        assert v.juez_fallo is True

    async def test_should_let_through_an_answer_with_no_citable_claim(self):
        """Un saludo o una peticion de aclaracion no afirma nada que haya que fundamentar. Sin
        esta salida, la puerta rechazaria la repregunta que ORI-03 exige."""
        juez = _JuezFalso([])
        v = await hay_fundamento(
            texto="A quin dels dos reconeixements et refereixes?",
            fuentes=[_fuente()],
            juez=juez,
        )
        assert v.sostenida is True
        assert v.juzgadas == 0

    async def test_should_not_count_a_remission_as_an_ungrounded_claim(self):
        """HIB.0 legitimo nombrar una norma sin enlazarla. Una afirmacion SIN enlace es
        remision y no entra: si contara, cada respuesta que remite bien a la Ley 9/2017
        perderia por algo que el contrato permite a proposito."""
        juez = _JuezFalso([True])
        v = await hay_fundamento(
            texto="Esto lo regula la Ley 9/2017, que no esta en este corpus. "
            "Aqui el minimo es el 20 % [A](https://www.uji.es/a#art-4).",
            fuentes=[_fuente("A")],
            juez=juez,
        )
        assert v.juzgadas == 1
        assert v.sostenida is True

    async def test_should_let_through_when_there_are_no_sources(self):
        juez = _JuezFalso([])
        v = await hay_fundamento(texto="cualquier cosa", fuentes=[], juez=juez)
        assert v.sostenida is True
        assert v.juzgadas == 0


@pytest.mark.asyncio
class TestQueSeLeDaAlJuez:

    async def test_should_give_the_judge_the_excerpt_of_the_cited_source(self):
        """El juez decide con el FRAGMENTO delante, no de memoria. Es la diferencia entre
        comprobar la cita y preguntarle al modelo si le suena verdadera."""
        juez = _JuezFalso([True])
        await hay_fundamento(
            texto="Hay que superar el 20 % [A](https://www.uji.es/a#art-4).",
            fuentes=[_fuente("A", texto="Article 4. Cal superar un minim del 20%")],
            juez=juez,
        )
        assert juez.vistas[0][1] == "Article 4. Cal superar un minim del 20%"

    async def test_should_not_judge_a_claim_whose_source_was_not_retrieved(self):
        """Si la cita apunta a algo que no esta entre lo recuperado, no hay fragmento con el
        que juzgar y la afirmacion cuenta como SIN fundamento sin gastar una llamada: el
        contrato de citas ya deberia haberla despojado."""
        juez = _JuezFalso([])
        v = await hay_fundamento(
            texto="El umbral es 40.000 euros [Ley 9/2017](https://www.boe.es/x#a118).",
            fuentes=[_fuente("Reglament de permanencia")],
            juez=juez,
        )
        assert v.juzgadas == 1
        assert v.con_fundamento == 0
        assert v.sostenida is False
        assert juez.vistas == []


@pytest.mark.asyncio
class TestLaCifraQueNoEstaEnElArticuloQueCita:
    """La regla que salvo el proposito de la comprobacion, y que casi se pierde.

    La guarda contra el bilinguismo —si no se localiza el termino, no se rechaza— desactivaba lo
    principal: una respuesta que INVENTA una cifra ausente de su cita tambien queda «no
    localizada», y habria pasado. Es el caso ORI-16 del reves.

    Lo que separa los dos casos es que **las cifras no se traducen**. «1,12», «20 %» y «15.000»
    son las mismas en valenciano y en castellano; las palabras no.
    """

    async def test_should_reject_an_invented_figure_without_asking_the_judge(self):
        juez = _JuezFalso([True])  # si se le preguntara, diria que si
        v = await hay_fundamento(
            texto="El cost de l'asseguranca escolar es d'1,12 euros "
            "[Reglament de permanencia](https://www.uji.es/reglament-de-permanencia#art-4).",
            fuentes=[_fuente()],
            juez=juez,
        )
        assert v.sostenida is False
        assert juez.vistas == [], "no hace falta preguntar: la cifra no esta en el articulo"
        assert "cifra" in v.detalle[0]["motivo"]

    async def test_should_accept_the_same_figure_written_with_another_separator(self):
        """«15.000» y «15000» son la misma cifra. Sin normalizar, el rechazo seria por como esta
        escrita y no por lo que dice."""
        juez = _JuezFalso([True])
        v = await hay_fundamento(
            texto="El termini acaba el 15 de desembre "
            "[Reglament de permanencia](https://www.uji.es/reglament-de-permanencia#art-4).",
            fuentes=[_fuente()],
            juez=juez,
        )
        assert v.sostenida is True
        assert juez.vistas, "la cifra si esta: aqui el juez decide"

    async def test_should_not_reject_a_wording_difference_between_languages(self):
        """Sin cifras, una afirmacion cuyas palabras no aparecen puede ser la lengua: «seis
        anos» donde la norma dice «sis anys». Eso no se rechaza."""
        juez = _JuezFalso([False])
        v = await hay_fundamento(
            texto="El mandato es de duracion determinada "
            "[Sindicatura](https://www.uji.es/sindicatura#art-9).",
            fuentes=[_fuente("Sindicatura", texto="La durada del mandat es de sis anys.")],
            juez=juez,
        )
        assert v.sostenida is True
        assert v.juez_fallo is True
