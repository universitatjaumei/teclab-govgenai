"""Partir `AGENTS.md` sólo funciona si sus punteros resuelven.

**Por qué existe.** `AGENTS.md` eran 40 KB y el 28 % duplicaba `docs/METODOLOGIA_AGENTICA.md`: las
cuatro causas de parada, el bucle, el informe de cierre y el protocolo de verificación estaban
escritos **dos veces**, con redacción distinta. Es una violación de la regla de «una sola fuente de
verdad por cosa» dentro del fichero que la enuncia, y ya costó una edición doble.

El corte deja en `AGENTS.md` el imperativo y manda el detalle al documento que lo explica. Eso
cambia el modo de fallo: antes el riesgo era divergir, y ahora es **apuntar al vacío**. Un puntero
roto en el fichero de reglas es peor que la duplicación, porque el agente se queda sin la regla y
sin saberlo.

**Y comprueba también que el imperativo no se fue con el relato.** Al condensar se perdió una
regla —el mensaje final del `.bat`— y sólo se detectó porque se comprobó marcador a marcador. Las
que se listan abajo son las que un agente necesita **antes** de escribir código: si alguna
desaparece de `AGENTS.md`, deja de obligar aunque siga escrita en otro sitio.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

#: `server/tests/infra/` → tres niveles arriba. Con `assert`, porque un test que recorre un
#: directorio inexistente pasa en verde sin mirar nada.
RAIZ = Path(__file__).resolve().parents[3]
assert (RAIZ / "docs").is_dir(), f"la raíz no es la que se cree: {RAIZ}"

REGLAS = RAIZ / "AGENTS.md"


@pytest.fixture(scope="module")
def agents() -> str:
    assert REGLAS.is_file(), "falta `AGENTS.md`, que es el fichero canónico de reglas"
    return REGLAS.read_text(encoding="utf-8")


def _rutas_citadas(texto: str) -> list[str]:
    """Las rutas del proyecto que el fichero cita entre acentos graves."""
    encontradas = sorted(
        set(re.findall(r"`((?:docs|planificacion|server|\.github)/[\w./-]+)`", texto))
    )
    assert encontradas, (
        "no se ha encontrado ninguna ruta citada en `AGENTS.md`. O el formato cambió —y entonces "
        "este test hay que reescribirlo— o la expresión regular está mal, que es peor porque "
        "dejaría el test pasando en el vacío."
    )
    return encontradas


class TestLosPunterosResuelven:
    """Un puntero roto deja al agente sin la regla y sin saberlo."""

    def test_should_point_at_things_that_exist(self, agents: str):
        rotos = [r for r in _rutas_citadas(agents) if not (RAIZ / r).exists()]
        assert not rotos, (
            f"`AGENTS.md` cita rutas que no existen: {rotos}. Desde que el fichero manda el "
            "detalle a otros documentos, un puntero roto es peor que la duplicación que se "
            "quitó: la regla desaparece sin que nada lo diga."
        )

    def test_should_point_at_the_document_that_holds_the_detail(self, agents: str):
        """El destino del detalle tiene que existir y tener las secciones que se citan."""
        destino = RAIZ / "docs" / "METODOLOGIA_AGENTICA.md"
        assert destino.is_file(), (
            "falta `docs/METODOLOGIA_AGENTICA.md`, que es donde vive el protocolo completo desde "
            "que `AGENTS.md` se quedó con el imperativo."
        )
        detalle = destino.read_text(encoding="utf-8")

        # Las secciones que `AGENTS.md` cita por número. Se recorta el punto final: la cita
        # aparece como «§3.» al acabar la frase, y sin recortarlo se busca una «§3..» que no
        # existe — mi propio instrumento mintiendo antes que el documento.
        for bruto in re.findall(r"METODOLOGIA_AGENTICA\.md` §([\d.]+)", agents):
            seccion = bruto.rstrip(".")
            assert f"## {seccion}." in detalle or f"### {seccion} " in detalle, (
                f"`AGENTS.md` manda a la §{seccion} de la metodología y esa sección no existe. "
                "Renumerar sin actualizar el puntero deja una regla inalcanzable."
            )


#: Lo que un agente necesita **antes** de escribir código. Si desaparece de `AGENTS.md`, deja de
#: obligar aunque siga escrito en otro documento: nadie lee el otro documento primero.
_IMPERATIVOS = {
    "el bloque no informa hasta cerrarse": "no informes hasta cerrarlo",
    "commit firmado por prompt": "git commit -s",
    "sin Co-Authored-By": "Co-Authored-By",
    "nunca a main": "Nunca commitees ni empujes a `main`",
    "las cuatro causas de parada": "Prerrequisito externo ausente",
    "cuándo NO interrumpir": "Cuándo NO interrumpir",
    "los tests escalonados": "Durante el prompt",
    "la suite desde Git Bash": "Git Bash",
    "CI con -n0": "-n0",
    "una cifra no medida no se reporta": "no se reporta como medida",
    "no se cambia de modelo solo": "No intentes cambiar de modelo",
    "el .bat es uno por bloque": "Uno por bloque",
    "la codificación del .bat": "cp1252",
    "verificar en navegador sin pedir permiso": "sin pedir permiso",
    "Docling no vuelve": "Docling no se reintroduce",
    "el edge necesita los modelos locales": "modo edge sigue necesitando",
    "la especificación, si cambió una garantía": "si cambió una garantía",
    "la madurez la mueve el despliegue": "La madurez la mueve el despliegue",
}


class TestElImperativoSeQuedaEnLasReglas:

    @pytest.mark.parametrize(("nombre", "marcador"), sorted(_IMPERATIVOS.items()))
    def test_should_keep_the_rule_in_agents_md(self, agents: str, nombre: str, marcador: str):
        assert marcador in agents, (
            f"la regla «{nombre}» ha desaparecido de `AGENTS.md`. Puede seguir explicada en otro "
            "documento, pero ahí no obliga: `AGENTS.md` es lo que se lee antes de escribir código. "
            "Si la regla se ha retirado a propósito, hay que quitarla también de este test — y "
            "entonces el rojo es la conversación que toca tener."
        )


class TestNoVuelveLaDuplicacion:
    """Lo que motivó el corte no puede volver por la puerta de atrás."""

    def test_should_not_rewrite_the_closing_report_in_two_places(self, agents: str):
        """La lista de qué lleva el informe de cierre vive en un sitio.

        Se comprobó escribiéndola dos veces: al añadir la línea de la especificación hubo que
        editarla en `AGENTS.md` y en la metodología, y la segunda casi se queda sin actualizar.
        `AGENTS.md` cita ahora los puntos por referencia.
        """
        assert "Antes de empezar / Ejecuta el archivo" not in agents, (
            "la plantilla de instrucciones al usuario ha vuelto a `AGENTS.md`. Vive en "
            "`docs/METODOLOGIA_AGENTICA.md` §7.1, que es donde se usa: al cerrar el bloque."
        )

    def test_should_stay_under_the_size_that_motivated_the_split(self, agents: str):
        """Un cable trampa contra el relato, no un presupuesto de bytes.

        **Qué está comprobado y qué no.** Comprobado: que la prosa histórica vuelve sola a este
        fichero —el listón saltó tres veces el 2026-09-23 y las tres veces lo que sobraba era
        narración de algo retirado, no una regla—. No comprobado: que el punto exacto sea 36, ni
        44, ni ningún otro. El estudio sobre ficheros de contexto encuentra que la longitud
        moderada funciona mejor y que los agentes se saltan lo verboso, pero no da una cifra para
        este fichero, y fingir que sí la da sería inventar una medida.

        **Por eso el número se eligió el 2026-09-23 por su holgura y no por su exactitud.** Estuvo
        en 36 porque era donde el fichero estaba al partirlo, y acabó regulando de más: tres
        reglas legítimas seguidas obligaron a recortar prosa buena para hacerles sitio, con seis
        bytes de margen. Un listón que se toca al añadir cualquier regla no mide el relato, mide
        el calendario — y el remedio que enseña es el equivocado: quitar adjetivos en vez de mover
        razonamiento.

        **Cuando esto se ponga rojo, la respuesta correcta sigue siendo la misma**: llevar el
        razonamiento largo a un documento aparte que este fichero enlace. Si la única forma de
        volver bajo el listón fuera recortar reglas, entonces el listón está mal y toca revisarlo
        otra vez, no comprimir hasta que quepa.
        """
        kb = len(agents.encode("utf-8")) / 1024
        assert kb < 44, (
            f"`AGENTS.md` ha crecido a {kb:.1f} KB. Antes de recortar, mira qué hay dentro: si lo "
            "que sobra es el relato de algo retirado, va al historial de git o al documento que "
            "lo cuenta entero. Si lo que sobra son reglas, el listón está mal puesto y se "
            "revisa; comprimir prosa hasta que quepa es lo único que no arregla nada."
        )
