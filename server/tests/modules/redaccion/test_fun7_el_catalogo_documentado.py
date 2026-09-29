"""FUN.7 — que `docs/CATALOGO_FUNCIONES.md` no mienta.

El prompt pide que las reglas del auditor se listen **desde el código y no copiadas a mano**, y la
razón es la de siempre en este proyecto: una lista copiada pasa en verde el día que el código
cambia, y entonces el documento que se le da a un equipo externo describe un auditor que no
existe. Es la misma clase de guardarraíl que `test_especificaciones_no_miente.py`: caza la deriva
**estructural**, no la prosa.

Lo que **no** puede comprobar es si la prosa sigue siendo verdad, y por eso el bloque también
escribe la petición explícita a la UADTI en el propio documento: un contraste con las Guías
Operativas Técnicas no lo puede hacer un test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[3].parent / "docs" / "CATALOGO_FUNCIONES.md"


@pytest.fixture(scope="module")
def documento() -> str:
    assert RUTA.exists(), f"no encuentro {RUTA}"
    return RUTA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def prosa(documento: str) -> str:
    """El documento con los espacios normalizados, para afirmar **frases**.

    Afirmar una frase sobre el texto crudo la hace rehén de dónde parte la línea: al reescribir
    §4 se rompió «en el nivel 2 no hay nada que aprobar» por un salto, y el guardarraíl dio rojo
    sin que faltara nada. Colapsar los blancos mantiene la garantía —la frase está— y quita la
    dependencia del formato. Lo estructural (encabezados, tablas) se sigue afirmando sobre el
    crudo, donde el formato **sí** importa.
    """
    import re

    return re.sub(r"\s+", " ", documento)


@pytest.fixture(scope="module")
def caja():
    from server.app.modules.redaccion.services.script_auditor import caja_de_herramientas

    return caja_de_herramientas()


class TestLasReglasDelAuditorSalenDelCodigo:

    def test_should_list_every_allowed_module(self, documento, caja):
        """Los 16 módulos permitidos, uno a uno. Si el auditor gana uno y el documento no, un
        equipo externo escribe código que la plataforma rechazaría por una razón que el documento
        no menciona; si lo pierde, escribe código que el documento permite y el auditor no."""
        faltan = [m for m in caja.modulos_permitidos if f"`{m}`" not in documento]

        assert faltan == [], (
            "módulos que el auditor permite y el documento no nombra: "
            f"{faltan}. La lista de §5 se copia del código, no se escribe de memoria."
        )

    def test_should_name_every_denied_capability(self, documento, caja):
        """Y las denegadas. Son muchas y están agrupadas por familia en el documento, pero cada
        una tiene que aparecer: la que falte es la que alguien usará."""
        faltan = [c for c in caja.capacidades_denegadas if f"`{c}`" not in documento]

        assert faltan == [], (
            f"capacidades denegadas que el documento no nombra: {faltan}"
        )

    def test_should_list_every_rule_with_its_level(self, documento, caja):
        """Con su nivel, porque la diferencia entre CRITICAL y WARNING **es** la diferencia entre
        «no se registra» y «se registra y lo mira la revisión posterior»."""
        for regla in caja.reglas:
            assert f"`{regla.id}`" in documento, f"la regla {regla.id} no está en el documento"
            # El nivel tiene que estar en la misma línea de la tabla que el id.
            linea = next(
                (
                    ln
                    for ln in documento.splitlines()
                    if f"`{regla.id}`" in ln and "|" in ln
                ),
                None,
            )
            assert linea is not None, f"la regla {regla.id} no está en la tabla de §5"
            assert regla.nivel.value in linea, (
                f"la regla {regla.id} aparece con un nivel distinto del que tiene el auditor "
                f"({regla.nivel.value}): «{linea.strip()}»"
            )

    def test_should_name_the_distribution_of_every_third_party_module(self, documento, caja):
        """AUT.9 — `import fitz` se instala como `pymupdf`, y §5 tiene que decirlo.

        **El «para qué sirve» no se comprueba aquí y es deliberado**: no está en el documento,
        lo sirve la API. Lo que sí está —porque es una decisión y no un dato de uso— es con qué
        nombre se instala cada módulo y qué licencia arrastra, y eso sí puede quedarse viejo.
        El caso real: alguien aprueba una librería cuyo nombre de importación no es el de la
        distribución, y quien escribe el guion fuera pone el `pip install` equivocado.
        """
        faltan = [
            f"{m.modulo}→{m.instala}"
            for m in caja.modulos
            if m.instala and f"`{m.instala}`" not in documento
        ]

        assert faltan == [], (
            f"módulos de terceros cuyo nombre de instalación no aparece en el documento: "
            f"{faltan}"
        )

    def test_should_not_invent_rules_the_auditor_does_not_have(self, documento, caja):
        """La otra mitad: una regla en el documento que el auditor no aplica es una promesa
        falsa, y es peor que una que falte."""
        import re

        ids_reales = {r.id for r in caja.reglas}
        # Los ids de regla son kebab-case y en el documento van en la tabla de §5.
        seccion = documento.split("## 5.")[1].split("## 6.")[0]
        citados = set(re.findall(r"`([a-z]+(?:-[a-z]+)+)`", seccion))
        # Se filtran los nombres de módulo y capacidad, que comparten la forma. Y los de
        # **distribución**, que también: un módulo se importa como `docx` y se instala como
        # `python-docx`, y §5 nombra las dos cosas a propósito —quien lea la lista tiene que
        # saber qué poner en el `pyproject.toml`—. Se enumeran en vez de aflojar el patrón:
        # añadir uno aquí es un acto visible, y una regla inventada sigue cayendo.
        distribuciones = {"python-docx"}
        candidatos = (
            citados
            - set(caja.modulos_permitidos)
            - set(caja.capacidades_denegadas)
            - distribuciones
        )

        inventados = candidatos - ids_reales

        assert inventados == set(), (
            f"el documento cita reglas que el auditor no tiene: {sorted(inventados)}"
        )


class TestLoQueElDocumentoTieneQueDecir:
    """Las secciones que el prompt exige, comprobadas por su existencia y no por su redacción.

    Un test no puede juzgar prosa. Lo que sí puede es impedir que una sección **desaparezca**, que
    es lo que pasa cuando alguien reescribe el documento y se salta la parte incómoda — y la parte
    incómoda aquí es justamente la que la OIATI tiene que leer.
    """

    @pytest.mark.parametrize(
        "seccion",
        [
            "## 1. Qué es una función, campo a campo",
            "## 2. El ciclo de una versión",
            "## 3. Quién puede qué",
            "## 4. Correspondencia con la Instrucció 02/2026",
            "## 5. La caja de herramientas del auditor",
            "## 6. Llevar tu script al catálogo",
            "## 7. Empaquetar una función",
            "## 8. Ejecutar una función por API",
            "## 9. El puente a Fase 3",
        ],
    )
    def test_should_have_the_section(self, documento, seccion):
        assert seccion in documento

    def test_should_keep_the_honest_difference_with_the_instruccio(self, prosa):
        """La diferencia con la regla 2 —el código va a los datos y no al equipo de la persona—
        y la petición explícita de un «sí» a UADTI y OIATI. Es la parte que un resumen
        entusiasta borraría primero."""
        assert "La diferencia honesta con la regla 2" in prosa
        assert "UADTI" in prosa and "OIATI" in prosa
        assert "no un silencio" in prosa

    def test_should_ask_the_uadti_to_contrast_the_rules(self, prosa):
        assert "Guías Operativas Técnicas" in prosa
        # Y el Anexo III.3, que es el que §8.4 cita para el análisis estático: citar sólo
        # las Guías dejaba fuera la referencia concreta de la norma.
        assert "Anexo III.3" in prosa

    def test_should_say_the_trust_boundary_without_softening_it(self, documento):
        """«Corre in-process, sin sandbox, y quien instala responde». Si esta frase se suaviza,
        el primer equipo externo cree que hay un aislamiento que no existe."""
        seccion = documento.split("## 7.")[1].split("## 8.")[0]
        assert "sin sandbox" in seccion
        assert "No hay" in seccion and "aislamiento" in seccion
        assert "pip install" in seccion

    def test_should_state_that_approving_is_not_a_review_outcome(self, prosa):
        """El invariante del nivel 2, escrito donde lo va a leer quien revise. Si el documento
        dijera que se «aprueba» una versión, la persona que revisa creería que su firma es lo que
        autoriza el uso."""
        assert "no hay nada que aprobar" in prosa

    def test_should_state_that_the_anchor_survives_publishing(self, prosa):
        assert "no cambia ninguna plantilla" in prosa


class TestLoQueElDocumentoNoPuedeDejarDePreguntar:
    """Las tres preguntas que §4 le hace a la institución, y los tres huecos que confiesa.

    Aparecieron al leer la Instrucció de verdad en vez del resumen que yo tenía escrito, y son
    justo lo que una reescritura «para dejarlo más limpio» borraría primero: son las partes donde
    el documento admite que la plataforma no puede decidir sola.
    """

    def test_should_not_equate_promotion_with_the_instruccios_level_three(self, prosa):
        """El nivel 3 de la Instrucció es **salir** del desarrollo ciudadano, no promover dentro
        del catálogo. Igualarlos haría creer que promover una función sustituye al circuito que la
        norma prevé para lo que excede un servicio."""
        assert "No tiene equivalente directo" in prosa

    def test_should_ask_whether_this_is_citizen_development_at_all(self, prosa):
        """La matriz de §4 de la Instrucció, que antes no se mencionaba y basta un criterio para
        derivar el caso. Es la pregunta anterior a la de la regla 2."""
        assert "¿esto es desarrollo ciudadano?" in prosa
        assert "indicadores de seguimiento o cuadros de mando" in prosa

    def test_should_frame_rule_two_as_end_or_means(self, prosa):
        """La pregunta acotada. Sin acotarla, la conversación se queda en «es distinto» y no se
        puede contestar."""
        assert "como fin" in prosa and "como medio" in prosa
        # Y el argumento que la hace contestable: la función no puede hablar con nada.
        assert "no puede hablar con nada" in prosa

    def test_should_keep_the_three_closed_gaps_with_their_decision(self, prosa):
        """Los tres huecos frente a la norma —plazo de revisión (§10), ruta a la OIATI (§9 y
        §8.4) y quién suspende (§9)— se cerraron el 2026-09-29 con las issues #122 y #123.

        **Este test cambió de sentido y no de sitio.** Antes exigía que los huecos se
        confesaran; ahora exige que la **decisión** siga escrita donde estaba la pregunta. Es lo
        mismo que protegía antes: que nadie tenga que reconstruir por qué el plazo son 30 días
        o por qué no hay una bandeja para la OIATI. Borrar los huecos al cerrarlos habría dejado
        el documento con las respuestas y sin las preguntas, que es como se vuelven a abrir.
        """
        assert "tres decisiones tomadas" in prosa
        assert "No hay plazo de revisión" in prosa
        assert "No hay ruta automática a la OIATI" in prosa
        # La tensión con §9 sigue nombrada: la decisión fue **no** coincidir con ella.
        assert "Responsable institucional de IA" in prosa
        assert "se hace fuera de la plataforma" in prosa

    def test_should_name_the_simplified_integration_study(self, prosa):
        """§8.2 pide la declaración **acompañada** de un estudio de integración simplificado
        (Anexo I). La declaración del catálogo son dos campos, y eso se dice."""
        assert "estudio de integración simplificado" in prosa
        assert "Anexo I" in prosa
