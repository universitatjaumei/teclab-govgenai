"""Las opciones que el panel necesita del contrato, no de su propio código (LANG.2).

Deploy: cloud
Módulo: chatbots

**Por qué un endpoint y no un `enum` del contrato**, que era la otra opción del plan:
`fixed:<código>` es un modo **paramétrico**, así que el conjunto de valores válidos no es
enumerable y un `Literal[...]` no puede expresarlo. Enumerable sí es la lista de *modos* —dos
simples y uno con parámetro— y la de *lenguas* que el panel puede ofrecer, que es exactamente lo
que hace falta para pintar un desplegable sin escribir los valores en React (regla maestra 1).

**Y cierra una trampa que la validación de LANG.1 no puede ver.** El corpus llama **`val`** al
valenciano, no `ca`: `services/language_detector.py` traduce `ca`→`val` porque «mientras los dos
códigos convivieron nunca coincidían», y de ahí venía que `prefer` metiera todo en el saco de
«otra lengua» en las preguntas en valenciano. Si el panel ofreciera «Valencià» y enviara
`fixed:ca`, el 422 de LANG.1 lo aceptaría —la **forma** es correcta— y el resultado sería una
preferencia que no prefiere ninguna versión de ninguna norma, en silencio. Así que las lenguas las
da el servidor con el código del corpus y el panel manda lo que le ofrecieron.

La validación sigue aceptando cualquier código de 2-3 letras a propósito: otra administración
puede desplegar esto en gallego o en euskera sin tocar el núcleo. **El catálogo es lo que el panel
ofrece, no lo único que la plataforma admite**, y ésa es la diferencia que permite las dos cosas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.app.api.deps import require_module, require_role
from server.app.core.auth.models import UserInfo, UserRole
from server.app.core.language_mode import (
    MODO_PREFERIR,
    MODO_SIN_POLITICA,
    PREFIJO_FIJO,
)

#: `require_module` y no sólo el rol: el docstring declara el módulo y **un docstring no
#: autoriza nada** —es lo que dejó `library_router` abierto pasando el check de PLAT.5 en
#: verde—. `chatbots` es donde viven las dos pantallas que consumen esto: la de chatbots y
#: la de valores por defecto de la organización.
router = APIRouter(
    prefix="/hub/opciones",
    tags=["hub-opciones"],
    dependencies=[Depends(require_module("chatbots"))],
)

#: Lo lee quien configura un chatbot o los valores por defecto de una organización, o sea
#: administrador o superadministrador. Un usuario no tiene nada que hacer con esto.
_require_admin = require_role(UserRole.SUPERADMIN.value, UserRole.ADMIN.value)


class ModoDeLengua(BaseModel):
    """Un modo de política de lengua, con lo que el panel necesita para pintarlo."""

    #: `prefer` | `none` | `fixed`. **Sin el código**: el panel compone `fixed:<código>` con la
    #: lengua que elija en el segundo desplegable, y por eso el valor de aquí no es un
    #: `language_mode` completo para el modo paramétrico.
    valor: str
    #: Si hace falta elegir además una lengua. Es lo que le dice al panel cuándo enseñar el
    #: segundo desplegable, en vez de que lo deduzca de que el valor sea «fixed».
    requiere_lengua: bool
    #: El de la cascada de plataforma. El panel no puede decidirlo por su cuenta.
    es_por_defecto: bool


class LenguaOfrecida(BaseModel):
    """Una lengua que el panel puede ofrecer, en el código que usa el corpus."""

    #: El código del **corpus** (`val`, `es`, `en`), no el de `langdetect`. Ver el docstring.
    codigo: str
    #: El nombre de la lengua **en esa lengua**: quien busca la suya la reconoce escrita así.
    #: Mismo criterio que el selector de idioma del panel.
    etiqueta: str


class OpcionesDeLengua(BaseModel):
    modos: list[ModoDeLengua]
    lenguas: list[LenguaOfrecida]


#: Las lenguas del corpus, con su nombre en ellas mismas. `val` y no `ca`, que es el punto.
_LENGUAS: tuple[tuple[str, str], ...] = (
    ("val", "Valencià"),
    ("es", "Castellano"),
    ("en", "English"),
)


@router.get("/lengua", response_model=OpcionesDeLengua, operation_id="opcionesDeLengua")
async def opciones_de_lengua(
    user: UserInfo = Depends(_require_admin),  # noqa: ARG001 — autoriza: se pide por su efecto
) -> OpcionesDeLengua:
    """Los modos de política de lengua y las lenguas que se pueden fijar.

    No toca la base de datos: es contrato, no dato de inquilino. El día que necesite una sesión
    será porque el catálogo dejó de ser contrato, y entonces hay que replanteárselo.
    """
    return OpcionesDeLengua(
        modos=[
            ModoDeLengua(valor=MODO_PREFERIR, requiere_lengua=False, es_por_defecto=True),
            ModoDeLengua(valor=MODO_SIN_POLITICA, requiere_lengua=False, es_por_defecto=False),
            ModoDeLengua(
                valor=PREFIJO_FIJO.rstrip(":"), requiere_lengua=True, es_por_defecto=False
            ),
        ],
        lenguas=[LenguaOfrecida(codigo=c, etiqueta=e) for c, e in _LENGUAS],
    )
