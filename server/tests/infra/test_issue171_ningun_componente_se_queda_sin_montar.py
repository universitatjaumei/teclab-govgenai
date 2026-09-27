"""Issue #171 — un componente o un *hook* que nadie monta tiene que decirlo.

**Por qué existe este test.** Cinco piezas del frontend estaban escritas, completas y probadas, y
**ninguna ruta las montaba ni ningún fichero las importaba**. No daban error, no salían en ningún
informe, y se descubrieron porque alguien fue a tocarlas por otra razón. Dos eran capacidades que
nadie podía usar —el autoguardado entero—; una era la versión anterior de una pantalla que ya
existe. Ninguna forma es benigna: un componente que nadie monta **no se prueba en uso**, así que
acumula defectos que nadie ve. En `ThemeEditor` había uno por el que «Guardar» dejaba pasar un
tema inválido, y llevaba ahí sin molestar a nadie.

**Mira el símbolo, no el nombre del fichero.** La primera medición de la issue dijo 3 y eran 5:
buscaba el nombre del fichero en cualquier contexto, así que
`import type { AutosaveStatus } from '../hooks/useAutosave'` contaba como uso y el hook salía
«vivo» cuando nadie lo llamaba. Importar un **tipo** no es montar nada: el tipo desaparece al
compilar. Así que aquí se buscan importaciones de valor del identificador exportado, y se
descartan `import type { X }` y `{ type X }`.

**Y distingue lo deliberado de lo olvidado.** Un guardarraíl que no deje declarar la espera se
desactiva el primer día. La salida es escribir en el propio fichero:

    // sin-montar: <por qué todavía no lo monta nadie>

que es la misma forma que `salida-por-consola:` en la #18 y `recorrido-acotado:` en la #159. La
marca no es un permiso permanente: es una frase que alguien tiene que poder defender leyéndola.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3] / "frontend" / "src"

MARCA = "sin-montar:"

#: Lo que no se recorre. No son excepciones: es que ahí no hay nada que montar.
EXCLUIDOS = (
    "shared/api/generated/",  # lo escribe Orval desde el contrato
    "__tests__/",
    "__mocks__/",
)

#: Puntos de entrada: los monta el navegador o el empaquetador, no un `import` de nadie, así
#: que de ellos no se comprueban las exportaciones. **Sus importaciones sí se leen**: `App.tsx`
#: es quien monta las páginas, y dejarlo fuera del recorrido las marcaba a todas como huérfanas
#: — 38 falsos positivos, que es justo como se desactiva un guardarraíl el primer día.
ENTRADAS = {
    "main.tsx",
    "App.tsx",
    "vite-env.d.ts",
}

#: `export function X`, `export const X`, `export class X`, `export default function X`.
_EXPORTA = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
#: Los tipos no se montan: desaparecen al compilar.
_EXPORTA_TIPO = re.compile(r"^export\s+(?:type|interface)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)


def _ficheros() -> list[Path]:
    encontrados = []
    for ruta in RAIZ.rglob("*.ts*"):
        relativa = ruta.relative_to(RAIZ).as_posix()
        if relativa.endswith(".d.ts") or ".test." in relativa or ".stories." in relativa:
            continue
        if any(trozo in relativa for trozo in EXCLUIDOS):
            continue
        encontrados.append(ruta)
    return sorted(encontrados)


def _es_componente_o_hook(nombre: str) -> bool:
    """Componentes en `PascalCase`, *hooks* con `use`. Lo demás no es una pieza de pantalla.

    La minúscula obligatoria descarta las constantes en `MAYUSCULAS_CON_GUIONES` —`CONTROLES`,
    `OPCIONES_I18N`, `VARIABLE_POR_COLOR`—, que empiezan por mayúscula y no son nada que montar.
    Sin ese matiz el guardarraíl señalaba cinco, y una de ellas es exactamente el falso positivo
    que la propia medición de la issue tuvo que corregir.
    """
    if re.match(r"^use[A-Z]", nombre):
        return True
    return bool(re.match(r"^[A-Z]", nombre)) and any(c.islower() for c in nombre)


def _importa_el_valor(texto: str, nombre: str) -> bool:
    """¿Este fichero importa `nombre` **como valor**?

    Descarta `import type { X } from …` y `import { type X } from …`, que es el error que hizo
    que la medición original diera 3 en vez de 5.
    """
    for bloque in re.finditer(
        r"import\s+(type\s+)?(\{[^}]*\}|[A-Za-z_$][\w$]*)[^;\n]*from", texto
    ):
        if bloque.group(1):  # `import type { … }`
            continue
        especificadores = bloque.group(2)
        if not especificadores.startswith("{"):
            if especificadores == nombre:
                return True
            continue
        for pieza in especificadores.strip("{}").split(","):
            pieza = pieza.strip()
            if not pieza or pieza.startswith("type "):
                continue
            # `X as Y` importa X.
            local = pieza.split(" as ")[0].strip()
            if local == nombre:
                return True
    # Un `lazy(() => import('…')).then(m => m.X)` o un re-export `export { X } from '…'`.
    if re.search(rf"\bm\.{re.escape(nombre)}\b", texto):
        return True
    if re.search(rf"^export\s+\{{[^}}]*\b{re.escape(nombre)}\b[^}}]*\}}\s+from", texto, re.M):
        return True
    return False


_COMENTARIO = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)


def _sin_comentarios(texto: str) -> str:
    """El código sin sus comentarios.

    Hace falta para no contar como uso una mención en prosa. `useCopilotAction` se nombra en su
    propio docstring —«el wizard activo llama a `useCopilotAction(kind, onApply)`»— y esa frase
    describe precisamente lo que **no** ocurre: bastaba para que el guardarraíl lo diera por
    vivo. Un medidor que cuenta la descripción de una capacidad como su uso no mide nada.
    """
    return _COMENTARIO.sub(" ", texto)


def _se_usa_en_su_propio_fichero(texto: str, nombre: str) -> bool:
    """Un símbolo que consume otro del mismo módulo no está huérfano.

    `useTheme` es el caso: lo llama `withTheme`, doce líneas más abajo, y nadie más. Contarlo
    como huérfano pediría retirar el accesor de un contexto que sí está montado.

    **Límite conocido y escrito a propósito**: si toda una cadena dentro de un mismo fichero está
    muerta, cada eslabón parece vivo. Este test encuentra módulos huérfanos, no grafos huérfanos;
    prometer lo segundo sería un rótulo que miente.
    """
    apariciones = len(re.findall(rf"\b{re.escape(nombre)}\b", _sin_comentarios(texto)))
    # Una es la propia exportación; dos o más significan que algo de aquí lo usa.
    return apariciones > 1


def _huerfanos() -> list[tuple[str, str]]:
    ficheros = _ficheros()
    textos = {ruta: ruta.read_text(encoding="utf-8", errors="ignore") for ruta in ficheros}

    huerfanos: list[tuple[str, str]] = []
    for ruta, texto in textos.items():
        if MARCA in texto or ruta.name in ENTRADAS:
            continue
        tipos = set(_EXPORTA_TIPO.findall(texto))
        for nombre in _EXPORTA.findall(texto):
            if nombre in tipos or not _es_componente_o_hook(nombre):
                continue
            if _se_usa_en_su_propio_fichero(texto, nombre):
                continue
            usado = any(
                _importa_el_valor(_sin_comentarios(otro_texto), nombre)
                for otra, otro_texto in textos.items()
                if otra != ruta
            )
            if not usado:
                huerfanos.append((ruta.relative_to(RAIZ).as_posix(), nombre))
    return huerfanos


class TestElGuardarrailMiraLoQueDice:
    """Un recorrido que no encuentra ficheros pasa en verde sin haber mirado nada."""

    def test_recorre_el_frontend_de_verdad(self):
        ficheros = _ficheros()

        assert len(ficheros) > 100, (
            f"sólo se ven {len(ficheros)} ficheros de `frontend/src`: este test no está mirando "
            "nada. Si la carpeta se movió, hay que arreglar la ruta, no bajar el número."
        )

    def test_sabe_distinguir_un_import_de_valor_de_uno_de_tipo(self):
        """Es el error que hizo que la primera medición dijera 3 cuando eran 5."""
        assert _importa_el_valor("import { useAutosave } from '../hooks/useAutosave'", "useAutosave")
        assert _importa_el_valor("import useAutosave from '../hooks/useAutosave'", "useAutosave")
        assert _importa_el_valor(
            "import { useAutosave as x } from '../hooks/useAutosave'", "useAutosave"
        )

        assert not _importa_el_valor(
            "import type { AutosaveStatus } from '../hooks/useAutosave'", "AutosaveStatus"
        )
        assert not _importa_el_valor(
            "import { type AutosaveStatus } from '../hooks/useAutosave'", "AutosaveStatus"
        )

    def test_una_mencion_en_un_comentario_no_es_un_uso(self):
        """Es lo que daba por vivo a `useCopilotAction`: su docstring lo nombra."""
        codigo = "/** llama a useCopilotAction(kind) */\nexport function useCopilotAction() {}"

        assert not _se_usa_en_su_propio_fichero(codigo, "useCopilotAction")
        assert _se_usa_en_su_propio_fichero(
            "export function useX() {}\nconst y = useX()", "useX"
        )

    def test_reconoce_los_dos_repartos_de_exportacion(self):
        assert set(_EXPORTA.findall("export function Panel() {}")) == {"Panel"}
        assert set(_EXPORTA.findall("export const usePanel = () => {}")) == {"usePanel"}
        assert set(_EXPORTA_TIPO.findall("export type PanelProps = {}")) == {"PanelProps"}


class TestNadaSeQuedaSinMontarEnSilencio:

    def test_ningun_componente_ni_hook_sin_importador(self):
        huerfanos = _huerfanos()

        assert not huerfanos, (
            "estos componentes o hooks no los importa nadie:\n"
            + "\n".join(f"  - {nombre} en {ruta}" for ruta, nombre in huerfanos)
            + "\n\nO se montan, o se retiran, o el fichero declara la espera con una línea\n"
            f"`// {MARCA} <por qué>`. Lo que no puede quedarse es código completo que nadie\n"
            "ejecuta: no se prueba en uso, así que acumula defectos que nadie ve."
        )
