"""Los avisos que emite GitHub se revisan solos, y no cuando alguien se acuerda.

**De dónde sale.** El 2026-09-23, antes de abrir el repositorio, el mantenedor lo dijo así: «lo
voy viendo y te voy diciendo, pero si se me pasa o se me olvida se queda por revisar». Es la
descripción exacta de un control que existe y no actúa. Este proyecto ya tiene la lección escrita
—«se cumple donde está mecanizado y se escapa donde sólo estaba escrito»—, así que la respuesta no
podía ser una línea más en `AGENTS.md`.

**Lo que ya estaba mecanizado, y por eso no se rehace.** El job `supply-chain` de `ci.yml` audita
los cinco locks en **cada** commit y bloquea; `avisos_aceptados.toml` es su única puerta de
salida, con cinco campos y caducidad; `test_dep7_las_aceptaciones_caducan.py` impide que esa lista
crezca en silencio.

**Lo que faltaba es lo que vive del lado de GitHub** y no se puede calcular desde el árbol: las PR
de actualización pendientes y los informes de la revisión automática de código.

**Hubo un tercer control y se retiró el mismo día.** Reconciliaba las alertas de la pestaña
Dependabot con `avisos_aceptados.toml`. No pudo ser: el `GITHUB_TOKEN` de Actions **no alcanza a
esas alertas** —«403 Resource not accessible by integration» en su primera ejecución real— y no
hay permiso de workflow que lo arregle. La alternativa, un token propio, quedó pendiente de
aprobación de la organización, y se decidió no insistir: ni pedir excepción a una política de
credenciales, ni romper que este repositorio **no tenga ni un secreto**. Lo esencial no se
pierde, porque las vulnerabilidades las bloquea `supply-chain` sin ningún token; lo que se pierde
es la reconciliación con la pestaña, y eso vuelve a depender de que alguien mire.

Ese episodio dejó la lección que este fichero defiende por encima de las demás: **el paso
distingue «no pude mirar» de «no hay nada»**. El 403 se supo porque la llamada comprobaba su
error. Sin esa comprobación, el job habría informado de cero alertas **en verde, para siempre**,
dando tranquilidad falsa sobre vulnerabilidades. Este proyecto ya se comió un guardarraíl que
recorría un directorio inexistente y pasaba en verde.

**Y los hilos de Copilot son una foto, no una vigilancia.** Copilot comenta cuando termina, que
suele ser después de que CI haya pasado, y no hay forma de que el check se entere: resolver un
hilo no emite ningún evento que Actions admita, y los runs que dispara Copilot llegan retenidos a
la espera de aprobación. El check dice la verdad del instante en que corre y se recalcula con un
push o a mano — por eso no debe ser una comprobación obligatoria.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
WORKFLOW = RAIZ / ".github" / "workflows" / "avisos.yml"

#: Los eventos que GitHub Actions admite en `on:`. Copiada de «Events that trigger workflows» el
#: 2026-09-23. No es decorativa: un evento que no esté en esta lista **no falla la validación**,
#: deja el workflow sin arrancar. Si GitHub añade uno nuevo y aquí falta, este test da un falso
#: rojo con el nombre delante, que es un modo de fallo barato de diagnosticar.
_EVENTOS_DE_ACTIONS = frozenset(
    {
        "branch_protection_rule", "check_run", "check_suite", "create", "delete", "deployment",
        "deployment_status", "discussion", "discussion_comment", "fork", "gollum",
        "issue_comment", "issues", "label", "merge_group", "milestone", "page_build", "public",
        "pull_request", "pull_request_review", "pull_request_review_comment",
        "pull_request_target", "push", "registry_package", "release", "repository_dispatch",
        "schedule", "status", "watch", "workflow_call", "workflow_dispatch", "workflow_run",
    }
)


@pytest.fixture(scope="module")
def texto() -> str:
    assert WORKFLOW.is_file(), (
        f"Falta {WORKFLOW.relative_to(RAIZ).as_posix()}. Es lo único que revisa los avisos que "
        f"GitHub emite y que no se pueden calcular desde el árbol."
    )
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def datos(texto: str) -> dict:
    return yaml.safe_load(texto)


def _disparadores(datos: dict) -> dict:
    # PyYAML lee el `on:` de un workflow como el booleano True, que es la trampa clásica de YAML
    # 1.1. Si algún día se arregla en la biblioteca, la clave literal sigue valiendo.
    return datos.get(True) or datos.get("on") or {}


def test_el_medidor_lee_el_workflow(datos: dict) -> None:
    # Sin esto, un `on:` que PyYAML no encontrara dejaría en verde a todos los test de abajo
    # comparando listas vacías contra listas vacías.
    assert _disparadores(datos), (
        "no se han podido leer los disparadores del workflow; los test que comprueban cuándo "
        "corre estarían comparando nada contra nada"
    )


def test_no_se_usa_un_disparador_que_no_existe(datos: dict) -> None:
    """`pull_request_review_thread` es un webhook, pero **no** un disparador de Actions.

    Esto se intentó y se midió el 2026-09-23. La revisión automática señaló —con razón— que
    resolver un hilo no emite `pull_request_review` (`submitted`) ni `pull_request_review_comment`
    (`created`), así que el check se quedaba rojo después de hacer exactamente lo que pedía. El
    arreglo obvio era escuchar `pull_request_review_thread`, que **existe como webhook**.

    **No existe como disparador de `on:`.** Y un `on:` con un evento desconocido no da un error de
    validación: crea una ejecución **sin ningún job** que aparece como fallo, y la deja así en
    cada push. Costó un commit averiguarlo, y sin este test costaría otro dentro de seis meses.

    El test mira los disparadores **parseados**, no el texto: nombrar el evento en un comentario
    para explicar por qué no se usa es justamente lo que hay que hacer, y una comprobación sobre
    el texto lo confundiría con usarlo. Al mirar la lista entera caza cualquier otro inventado.
    """
    invalidos = sorted(set(_disparadores(datos)) - _EVENTOS_DE_ACTIONS)
    assert not invalidos, (
        f"el workflow declara disparadores que Actions no admite: {invalidos}. Un `on:` con un "
        f"evento desconocido no da error de validación: deja el workflow **sin arrancar**, con "
        f"una ejecución sin ningún job marcada como fallo en cada push. Pasó con "
        f"`pull_request_review_thread`, que existe como webhook y no como disparador."
    )


def test_las_actualizaciones_pendientes_se_ven_al_desplegar(datos: dict) -> None:
    ramas = (_disparadores(datos).get("push") or {}).get("branches") or []
    assert "main" in ramas, (
        "el workflow no corre al empujar a `main`. Ése es el momento en que se mira todo lo "
        "demás, y es donde se pidió que las actualizaciones pendientes estuvieran a la vista."
    )


def test_los_informes_de_copilot_se_revisan_antes_de_mezclar(datos: dict) -> None:
    disparadores = _disparadores(datos)
    assert "pull_request" in disparadores, "el workflow no corre en las PR"

    faltan = [
        evento
        for evento in ("pull_request_review", "pull_request_review_comment")
        if evento not in disparadores
    ]
    assert not faltan, (
        f"el workflow no escucha {faltan}. Copilot comenta cuando termina, normalmente después "
        f"de que CI haya pasado: sin estos disparadores el control tendría una sola oportunidad "
        f"de mirar, y sería la única en que todavía no había nada que ver."
    )


def test_hay_una_revision_periodica(datos: dict) -> None:
    assert _disparadores(datos).get("schedule"), (
        "no hay `schedule`. Una actualización puede quedarse esperando dos semanas sin que nadie "
        "toque el repositorio, y entonces ningún disparador por evento la mostraría."
    )


def test_declara_permisos_y_no_pide_escritura(datos: dict) -> None:
    # APER.8 ya exige `permissions` en la raíz de todo workflow; esto lo repite en corto para que
    # el fallo señale a este fichero y no a un test genérico.
    permisos = datos.get("permissions")
    assert permisos, "el workflow no declara `permissions` en la raíz"
    escrituras = [k for k, v in permisos.items() if v == "write"]
    assert not escrituras, (
        f"el workflow pide escritura en {escrituras}. Sólo lee avisos: no tiene por qué poder "
        f"cambiar nada."
    )


def test_no_usa_ningun_secreto(texto: str) -> None:
    """Este repositorio no tiene ni un secreto, y esa propiedad se conserva a propósito.

    El despliegue a GCP funciona con federación de identidad —sin claves que custodiar, rotar o
    revocar—, y las catorce entradas de configuración son variables, no secretos. Cuando la
    reconciliación de alertas necesitó un token propio, se retiró el control antes que introducir
    el primer secreto y pedir una excepción a la política de credenciales de la organización.

    Si alguna vez hace falta uno de verdad, que sea una decisión y no una deriva: este test se
    pone rojo y obliga a escribir por qué.

    La primera versión buscaba `secrets.NOMBRE` con una expresión regular, y **tenía un agujero**
    que señaló la revisión automática: las expresiones de GitHub admiten también la forma
    indexada, `secrets['NOMBRE']`, y de propina `toJSON(secrets)`. Un patrón que enumera formas
    sintácticas se queda corto en cuanto aparece una que no se te ocurrió.

    Así que la comprobación va al revés: se extraen **todas** las expresiones `${{ … }}` del
    fichero y se exige que ninguna nombre el contexto `secrets`, sea como sea que lo escriba. Es
    la diferencia entre prohibir las formas que conoces y prohibir lo que de verdad quieres
    prohibir.
    """
    expresiones = re.findall(r"\$\{\{(.*?)\}\}", texto, re.DOTALL)
    assert expresiones, (
        "no se ha encontrado ninguna expresión `${{ … }}` en el workflow. O dejó de usarlas, o "
        "el patrón dejó de reconocerlas: en el segundo caso este test aprobaría cualquier cosa."
    )

    con_secretos = [e.strip()[:80] for e in expresiones if re.search(r"\bsecrets\b", e)]
    assert not con_secretos, (
        f"estas expresiones usan el contexto `secrets`: {con_secretos}. Este repositorio no "
        f"tiene ningún secreto: despliega con federación de identidad y sus catorce entradas de "
        f"configuración son variables. Introducir el primero es una decisión que se escribe, no "
        f"un cambio de línea."
    )


def test_el_hueco_se_dice_tambien_cuando_no_hay_nada_que_contar(texto: str) -> None:
    """El aviso de que las alertas no se miran tiene que salir en los dos caminos.

    La primera versión lo escribía sólo después de listar las PR pendientes, así que **el día que
    no hubiera ninguna** —el caso tranquilo, el que más se repite— el resumen decía «Ninguna.» y
    nada más. Un informe que en su mes más tranquilo omite justo la parte que no cubre se lee como
    tranquilidad completa, y no lo es. Lo señaló la revisión automática.
    """
    assert "aviso_del_hueco()" in texto, (
        "el aviso del hueco ya no está factorizado en una función. Se sacó a una a propósito: "
        "duplicado en dos ramas, se corrige una y se olvida la otra."
    )
    invocaciones = len(re.findall(r"^\s*aviso_del_hueco\s*$", texto, re.MULTILINE))
    assert invocaciones >= 2, (
        f"el aviso del hueco se invoca {invocaciones} vez/veces. Tiene que salir en los dos "
        f"caminos —haya PR pendientes o no—, porque el camino silencioso es precisamente el que "
        f"más se lee y el que más engaña si se calla lo que no cubre."
    )


def test_no_mirar_no_es_no_haber_nada(texto: str) -> None:
    """Toda llamada a la API tiene su rama de error, y esa rama es roja.

    No es una preferencia de estilo: es lo que hizo que se supiera que el token de Actions no
    alcanza a las alertas de Dependabot. La llamada comprobó su error y el job dijo «403». Sin la
    comprobación habría dicho «ninguna alerta abierta», en verde, indefinidamente.
    """
    # Se mira línea a línea y no con dos conteos globales. Un primer intento comparaba «cuántas
    # protegidas» contra «cuántas hay», y **no cazaba nada**: los dos patrones anclaban al
    # principio de línea, así que al quitar el `if !` la llamada desaparecía de los dos lados a
    # la vez y la igualdad seguía cumpliéndose. Es el caso de libro de un medidor que mide su
    # propio reflejo.
    invocacion = re.compile(r"\bgh (?:api|pr) ")
    protegida = re.compile(r"^\s*if\s+!\s+[A-Z_]+=\"\$\(gh (?:api|pr) ")

    todas = texto.splitlines()
    indices = [
        i
        for i, linea in enumerate(todas)
        if invocacion.search(linea) and not linea.lstrip().startswith("#")
    ]
    lineas = [todas[i] for i in indices]
    assert lineas, (
        "no se encuentra ninguna llamada a `gh api` ni `gh pr`. O el workflow dejó de consultar "
        "nada, o el patrón dejó de reconocer cómo se escriben: en los dos casos, los test de "
        "abajo estarían comprobando el vacío."
    )

    sin_proteger = [linea.strip()[:90] for linea in lineas if not protegida.match(linea)]
    assert not sin_proteger, (
        f"estas llamadas no comprueban su error: {sin_proteger}. Una llamada suelta deja la "
        f"variable vacía cuando falla, y el paso informa de cero **en verde**. Así se supo que "
        f"el token de Actions no alcanza a las alertas de Dependabot: porque la llamada sí lo "
        f"comprobaba."
    )

    # Y comprobar el error no basta: la rama tiene que **terminar el paso**. Un `echo` de aviso
    # dentro de un job que acaba en verde es indistinguible de no haber mirado, que es justo lo
    # que este fichero defiende. Esta comprobación estaba en la primera versión, se perdió al
    # reescribir el test, y la echó de menos la revisión automática.
    #
    # Se recorre hasta el `fi` que cierra el bloque, no una ventana de N caracteres. Con ventana
    # fija fallaba en falso: la consulta GraphQL ocupa veinte líneas entre el `if !` y su rama de
    # error, y ninguna cifra redonda vale para las dos llamadas a la vez.
    for i, linea in zip(indices, lineas, strict=True):
        cierre = next(
            (j for j in range(i + 1, len(todas)) if todas[j].strip() == "fi"), None
        )
        assert cierre is not None, (
            f"la llamada `{linea.strip()[:70]}` abre un `if !` que no se cierra con un `fi`. O "
            f"el guion está roto, o este test ya no sabe leerlo."
        )
        rama = "\n".join(todas[i:cierre])
        assert "::error::" in rama, (
            f"la llamada `{linea.strip()[:70]}` comprueba su error pero su rama no pone el paso "
            f"en rojo. Hace falta un `::error::` y un `exit 1`: avisar en el registro y seguir "
            f"adelante deja el job verde, y un verde es lo único que nadie va a mirar."
        )
        assert "exit 1" in rama, (
            f"la llamada `{linea.strip()[:70]}` comprueba su error pero su rama no pone el paso "
            f"en rojo. Hace falta un `::error::` y un `exit 1`: avisar en el registro y seguir "
            f"adelante deja el job verde, y un verde es lo único que nadie va a mirar."
        )


def test_ninguna_llamada_a_avisos_se_silencia(texto: str) -> None:
    silenciadas = [
        linea.strip()
        for linea in texto.splitlines()
        if re.search(r"\bgh (api|pr)\b", linea)
        and ("|| true" in linea or "2>/dev/null" in linea)
    ]
    assert not silenciadas, (
        f"hay llamadas a la API con el error silenciado: {silenciadas}. Un fallo tragado aquí se "
        f"lee exactamente igual que «no hay avisos»."
    )
