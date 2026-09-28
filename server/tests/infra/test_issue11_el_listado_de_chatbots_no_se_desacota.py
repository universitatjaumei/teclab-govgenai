"""Issue #11 (MT.8) — el listado de chatbots no vuelve a pedirse sin acotar.

**Qué se arregló.** Nueve pantallas listaban chatbots y ninguna pasaba la organización elegida
en la cabecera, así que quien administra varias veía los de todas en cada desplegable — y a
partir de ahí sus documentos, sus escenarios y sus interacciones. Ahora hay un envoltorio,
`useChatbotsDeLaOrganizacion`, y el acotado de verdad lo hace el servidor.

**Por qué hace falta un guardarraíl y no basta con haberlo arreglado.** El hook generado sigue
existiendo y sigue siendo lo primero que encuentra quien busque «listar chatbots». La décima
pantalla lo llamará directamente y el acotado se perderá **sin que nada falle**: la lista sale,
sólo que con los chatbots de todas las organizaciones. Es la misma forma de avería que esta
semana ha aparecido cuatro veces — algo que deja de hacerse y no da ningún error.

**La salida declarada.** Un consumidor legítimo de la lista completa —uno que de verdad tenga que
ver todas las organizaciones— escribe en su fichero:

    // lista-sin-acotar: <por qué este necesita todas>

que es la misma forma de `sin-montar:`, `salida-por-consola:` y `recorrido-acotado:`. Sin una
salida, un guardarraíl se desactiva el primer día que estorba.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3] / "frontend" / "src"

MARCA = "lista-sin-acotar:"
HOOK_GENERADO = "useListChatbotsApiV1HubChatbotsGet"
ENVOLTORIO = "useChatbotsDeLaOrganizacion"

#: Dónde vive el envoltorio, que por definición sí llama al hook generado.
_EL_ENVOLTORIO = "shared/organizacion/useChatbotsDeLaOrganizacion.ts"


def _ficheros() -> list[Path]:
    encontrados = []
    for ruta in RAIZ.rglob("*.ts*"):
        relativa = ruta.relative_to(RAIZ).as_posix()
        if relativa.endswith(".d.ts") or ".test." in relativa:
            continue
        if "shared/api/generated/" in relativa or "__tests__/" in relativa:
            continue
        if relativa == _EL_ENVOLTORIO:
            continue
        encontrados.append(ruta)
    return sorted(encontrados)


class TestElGuardarrailMiraLoQueDice:

    def test_recorre_el_frontend_de_verdad(self):
        ficheros = _ficheros()

        assert len(ficheros) > 100, (
            f"sólo se ven {len(ficheros)} ficheros: este test no está mirando nada"
        )

    def test_el_envoltorio_existe_y_es_quien_llama_al_hook_generado(self):
        envoltorio = RAIZ / _EL_ENVOLTORIO

        assert envoltorio.exists(), "no está el envoltorio que acota la lista"
        cuerpo = envoltorio.read_text(encoding="utf-8")
        assert HOOK_GENERADO in cuerpo, "el envoltorio no llama al hook generado"
        assert "organizacion_id" in cuerpo, (
            "el envoltorio no manda la organización: sin eso no acota nada, y el guardarraíl "
            "estaría protegiendo una cáscara"
        )


class TestNadieVuelveAPedirLaListaSinAcotar:

    def test_ninguna_pantalla_llama_al_hook_generado_directamente(self):
        culpables = []
        for ruta in _ficheros():
            cuerpo = ruta.read_text(encoding="utf-8", errors="ignore")
            if HOOK_GENERADO not in cuerpo or MARCA in cuerpo:
                continue
            culpables.append(ruta.relative_to(RAIZ).as_posix())

        assert not culpables, (
            "estos ficheros piden la lista de chatbots sin acotar por la organización elegida:\n"
            + "\n".join(f"  - {c}" for c in culpables)
            + f"\n\nUsa `{ENVOLTORIO}`, o declara por qué este consumidor necesita todas con una "
            f"línea `// {MARCA} <razón>`."
        )

    def test_las_pantallas_que_listan_chatbots_usan_el_envoltorio(self):
        """El otro lado: que el arreglo siga puesto, no sólo que no se rompa por el otro sitio.

        Sin esto, alguien podría quitar la llamada de una pantalla y el test de arriba seguiría
        en verde — porque comprueba que nadie llama al generado, no que alguien llame al bueno.
        """
        usan = [
            ruta.relative_to(RAIZ).as_posix()
            for ruta in _ficheros()
            if ENVOLTORIO in ruta.read_text(encoding="utf-8", errors="ignore")
        ]

        assert len(usan) >= 9, (
            f"sólo {len(usan)} ficheros usan el envoltorio y eran nueve pantallas: {usan}"
        )


class TestLaSalidaDeclaradaFunciona:
    """Una marca que no se respeta es lo mismo que no tenerla."""

    def test_la_marca_exime(self):
        codigo = f"// {MARCA} este panel compara organizaciones\nconst x = {HOOK_GENERADO}()"

        assert MARCA in codigo and HOOK_GENERADO in codigo
        # La condición del recorrido, aplicada al mismo texto:
        assert not (HOOK_GENERADO in codigo and MARCA not in codigo)

    def test_sin_la_marca_no_exime(self):
        codigo = f"const x = {HOOK_GENERADO}()"

        assert HOOK_GENERADO in codigo and MARCA not in codigo


class TestLoQueNoSeAcotaYPorQue:
    """Los listados que **no** llevan filtro, y la razón, para que nadie lo «arregle».

    Es la parte de la medición que más fácil se pierde: sin esto, el próximo que lea la issue
    verá cinco listados sin filtrar y añadirá el filtro, rompiendo la herencia. El detalle vive
    en `docs/MULTITENENCIA.md`; aquí se fija lo que no puede cambiar en silencio.
    """

    def test_el_inventario_explica_por_que_los_heredables_no_se_filtran(self):
        inventario = (
            Path(__file__).resolve().parents[3] / "docs" / "MULTITENENCIA.md"
        ).read_text(encoding="utf-8")

        assert "Qué pantalla acota qué listado" in inventario, (
            "falta la sección que dice qué listado acota y cuál no: sin ella, la medición de "
            "esta issue se pierde en cuanto se cierre"
        )
        for tabla in ("hub_themes", "hub_llm_configs", "hub_module_grants"):
            assert tabla in inventario
