"""LANG.2 — el catálogo de modos de lengua lo sirve el servidor.

**Por qué un endpoint y no un `enum` del contrato**, que era la otra opción del plan: `fixed:<código>`
es un modo **paramétrico**, así que el conjunto de valores válidos no es enumerable y un
`Literal[...]` en el contrato no puede expresarlo. Lo que sí es enumerable es la lista de *modos*
—dos simples y uno con parámetro— y la lista de *lenguas* que el panel puede ofrecer, y eso es
justamente lo que hace falta para pintar un desplegable sin escribir los valores en React (regla
maestra 1).

**Y hay una trampa que este endpoint existe para cerrar.** El corpus llama **`val`** al valenciano,
no `ca`: `services/language_detector.py` traduce `ca`→`val` precisamente porque «mientras los dos
códigos convivieron nunca coincidían», y de ahí venía que `prefer` metiera todo en el saco de
«otra lengua» en las preguntas en valenciano. Si el panel ofreciera «Valencià» y enviara
`fixed:ca`, la validación de LANG.1 lo aceptaría —la forma es correcta— y el resultado sería una
preferencia que **no prefiere ninguna versión de ninguna norma**, en silencio. Por eso las lenguas
las da el servidor con el código del corpus, y el panel manda lo que le ofrecieron.

La validación de LANG.1 sigue aceptando cualquier código de 2-3 letras a propósito: otra
administración puede desplegar esto en gallego o en euskera sin que haya que tocar el núcleo. El
catálogo es lo que el panel **ofrece**, no lo único que la plataforma **admite**.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo


def _principal(role: str = "admin") -> UserInfo:
    return UserInfo(
        user_id="quien-administra",
        email="admin@uji.es",
        role=role,
        organizacion_ids=("735a5f55-7020-4c88-a374-c2b641c5b00b",),
    )


def _cliente(principal: UserInfo) -> AsyncClient:
    from server.app.routers.hub_opciones_router import router

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestElCatalogoDeModos:

    async def test_should_offer_the_three_modes(self):
        async with _cliente(_principal()) as c:
            r = await c.get("/api/v1/hub/opciones/lengua")

        assert r.status_code == 200, r.text
        assert [m["valor"] for m in r.json()["modos"]] == ["prefer", "none", "fixed"]

    async def test_should_say_which_mode_needs_a_language(self):
        """Es lo que le dice al panel cuándo enseñar el segundo desplegable."""
        async with _cliente(_principal()) as c:
            modos = {m["valor"]: m for m in (await c.get("/api/v1/hub/opciones/lengua")).json()["modos"]}

        assert modos["fixed"]["requiere_lengua"] is True
        assert modos["prefer"]["requiere_lengua"] is False
        assert modos["none"]["requiere_lengua"] is False

    async def test_should_say_which_mode_is_the_default(self):
        """El panel no puede decidir el defecto: `prefer` es el de la cascada de plataforma."""
        async with _cliente(_principal()) as c:
            modos = {m["valor"]: m for m in (await c.get("/api/v1/hub/opciones/lengua")).json()["modos"]}

        assert modos["prefer"]["es_por_defecto"] is True
        assert [m for m in modos.values() if m["es_por_defecto"]] == [modos["prefer"]]


class TestElCatalogoDeLenguas:

    async def test_should_use_the_corpus_code_for_valencian(self):
        """`val`, no `ca`. Ver el docstring del módulo: `fixed:ca` no casaría con nada."""
        async with _cliente(_principal()) as c:
            lenguas = (await c.get("/api/v1/hub/opciones/lengua")).json()["lenguas"]

        codigos = [lengua["codigo"] for lengua in lenguas]
        assert "val" in codigos
        assert "ca" not in codigos, (
            "el corpus llama `val` al valenciano; ofrecer `ca` daría una preferencia que no "
            "prefiere ninguna versión de ninguna norma, y en silencio"
        )

    async def test_should_offer_the_languages_the_corpus_has(self):
        async with _cliente(_principal()) as c:
            lenguas = (await c.get("/api/v1/hub/opciones/lengua")).json()["lenguas"]

        assert {"val", "es", "en"} <= {lengua["codigo"] for lengua in lenguas}

    async def test_should_carry_a_label_for_each_language(self):
        """El nombre de cada lengua **en esa lengua**: quien busca la suya la reconoce escrita así."""
        async with _cliente(_principal()) as c:
            lenguas = {elemento["codigo"]: elemento for elemento in (await c.get("/api/v1/hub/opciones/lengua")).json()["lenguas"]}

        assert lenguas["val"]["etiqueta"] == "Valencià"
        assert lenguas["es"]["etiqueta"] == "Castellano"

    async def test_should_produce_valid_modes_when_combined(self):
        """El contrato tiene que cerrar: lo que el catálogo ofrece, la validación lo acepta.

        Sin este test el endpoint podría ofrecer un código que el 422 de LANG.1 rechaza, y el
        panel enseñaría una opción que no se puede guardar.
        """
        from server.app.core.language_mode import PREFIJO_FIJO, valida_language_mode

        async with _cliente(_principal()) as c:
            datos = (await c.get("/api/v1/hub/opciones/lengua")).json()

        for modo in datos["modos"]:
            if modo["requiere_lengua"]:
                for lengua in datos["lenguas"]:
                    valor = f"{PREFIJO_FIJO}{lengua['codigo']}"
                    assert valida_language_mode(valor) == valor
            else:
                assert valida_language_mode(modo["valor"]) == modo["valor"]


class TestQuienPuedeLeerlo:

    async def test_should_refuse_someone_who_does_not_administer(self):
        async with _cliente(_principal(role="user")) as c:
            r = await c.get("/api/v1/hub/opciones/lengua")

        assert r.status_code == 403, r.text

    async def test_should_let_an_organization_admin_read_it(self):
        """Quien configura un chatbot de su organización necesita el catálogo para el desplegable."""
        async with _cliente(_principal(role="admin")) as c:
            r = await c.get("/api/v1/hub/opciones/lengua")

        assert r.status_code == 200


class TestElRouterEstaRegistrado:
    """Un endpoint que no está en `main.py` es un endpoint que el panel no puede llamar."""

    def test_should_be_served_by_the_application(self):
        from server.app.main import app
        from server.tests.rutas import caminos

        rutas = caminos(app)
        assert "/api/v1/hub/opciones/lengua" in rutas

    def test_should_be_registered_as_cloud(self):
        """Es configuración que lee el panel, no operación sobre datos del cliente."""
        import inspect

        from server.app.main import _register_cloud

        assert "hub_opciones_router" in inspect.getsource(_register_cloud)


@pytest.fixture(autouse=True)
def _sin_base_de_datos():
    """El catálogo no toca la base: es contrato, no dato de inquilino.

    Se deja dicho como fixture vacía porque su ausencia es la observación: si algún día este
    endpoint necesitara `get_session`, es que el catálogo dejó de ser contrato.
    """
    return
