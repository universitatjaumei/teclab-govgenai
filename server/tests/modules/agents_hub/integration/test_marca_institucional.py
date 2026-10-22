"""La marca de la institución es dato de configuración, no un asset del repositorio.

El panel de administración importaba el logotipo de la Universitat Jaume I como código
fuente (`import logoUji from '@/assets/logo-uji.png'` en `AppLayout.tsx`), y había una
excepción en `.gitignore` más un guardarraíl en integración continua que **garantizaban**
que ese fichero viajara al repositorio principal. Cualquier institución que clonara el
proyecto arrancaba con la marca de otra en su barra lateral.

La cascada visual ya existía —`hub_themes`, con `organizacion_id` nulo para la plataforma,
poblado para la organización y `chatbot_id` para el asistente— y el propio docstring de
`get_theme` decía que un tema «lleva los colores, **el logotipo** y el nombre de la
organización». El logotipo era lo único que no llevaba.

Tres cosas que estos tests fijan y que son fáciles de hacer mal:

- **`/resolved` va registrado antes de `/{theme_id}`.** FastAPI resuelve por orden de
  registro, y `_assert_id_de_tema` rechaza lo que no sea un UUID: registrado después, la
  ruta nueva contestaría «Identificador de tema inválido» y el fallo parecería del cliente.
- **La cascada fusiona en profundidad.** Si reemplazara, una organización que solo quiere
  su logotipo perdería la paleta de la plataforma sin pedirlo.
- **El logotipo se sirve sin cabecera de autorización.** Un `<img src>` no manda
  `Authorization`, así que exigirla convierte la marca en un icono roto. Lo que no puede
  pasar es que ese endpoint devuelva algo más que los bytes de la imagen.

El cliente es `AsyncClient` sobre `ASGITransport` y no `TestClient`: el segundo levanta su
propio bucle de eventos, y la sesión de `db_session` pertenece al del test, así que las
peticiones morían en «attached to a different loop».
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Mismo orden de importación que el resto de la suite: `server.app.main` primero, para que
# torch entre antes que cualquier motor de BD (ver el conftest de agents_hub).
import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.core.storage import get_storage_service
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.routers.hub_themes_router import router

PNG = b"\x89PNG\r\n\x1a\n" + b"contenido de un logotipo"
JPEG = b"\xff\xd8\xff" + b"contenido de un logotipo"


class AlmacenFalso:
    """`StorageService` en memoria: lo que importa es qué clave se escribe, no dónde."""

    def __init__(self) -> None:
        self.objetos: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objetos[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.objetos:
            raise FileNotFoundError(key)
        return self.objetos[key]

    async def delete(self, key: str) -> None:
        self.objetos.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objetos


def _principal(role="admin", organizacion_ids=()) -> UserInfo:
    return UserInfo(
        user_id="u-1",
        email="admin@test.com",
        role=role,
        organizacion_ids=tuple(str(o) for o in organizacion_ids),
    )


def _cliente(session, principal: UserInfo | None, almacen=None) -> AsyncClient:
    """`principal` a `None` monta la aplicación **sin sesión**, para probar lo público."""

    async def _sesion():
        yield session

    app = FastAPI()
    if principal is not None:
        app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_async_session] = _sesion
    app.dependency_overrides[get_storage_service] = lambda: almacen or AlmacenFalso()
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _organizacion(session, nombre="Organización de prueba"):
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    org = HubOrganizacion(id=uuid.uuid4(), name=nombre, partner_id="p1")
    session.add(org)
    await session.commit()
    return org


async def _tema(session, *, config, organizacion_id=None, is_default=False, name="Tema"):
    from server.app.modules.agents_hub.database.config_models import HubTheme

    tema = HubTheme(
        id=uuid.uuid4(),
        name=name,
        organizacion_id=organizacion_id,
        config=config,
        is_default=is_default,
        created_by="root",
    )
    session.add(tema)
    await session.commit()
    return tema


def _en_texto(cuerpo) -> str:
    return json.dumps(cuerpo, ensure_ascii=False)


# ───────────────────────── El contrato lleva la marca ─────────────────────────


class TestElContratoDelTemaLlevaLaMarca:

    def test_should_expose_branding_in_the_theme_contract(self):
        """Sin campo en el contrato no hay dónde configurarla, y de ahí venía el import."""
        from server.app.routers.hub_themes_router import ThemeConfig

        config = ThemeConfig(name="institucional")

        assert config.branding.logoUrl is None
        assert config.branding.logoAlt is None

    def test_should_accept_a_mark_without_touching_the_repository(self):
        from server.app.routers.hub_themes_router import ThemeConfig

        config = ThemeConfig(
            name="institucional",
            branding={"logoUrl": "/api/v1/hub/themes/x/logo", "logoAlt": "Ayuntamiento"},
        )

        assert config.branding.logoAlt == "Ayuntamiento"


# ───────────────────────── La cascada resuelve la marca ─────────────────────────


class TestLaCascadaResuelveLaMarca:

    @pytest.mark.asyncio
    async def test_should_fall_back_to_the_platform_theme(self, db_session):
        """Sin tema propio, la organización hereda el de plataforma."""
        await _tema(
            db_session,
            name="Plataforma",
            config={"name": "plataforma", "branding": {"logoAlt": "Gov Gen AI Platform"}},
        )
        org = await _organizacion(db_session)

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            respuesta = await cliente.get("/api/v1/hub/themes/resolved")

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["config"]["branding"]["logoAlt"] == "Gov Gen AI Platform"

    @pytest.mark.asyncio
    async def test_should_let_the_organization_override_the_platform_mark(self, db_session):
        """Lo que la organización no define lo sigue poniendo la plataforma: es una
        cascada, no un reemplazo. Con reemplazo, configurar el logotipo obligaría a volver
        a declarar la paleta entera para no perderla."""
        await _tema(
            db_session,
            name="Plataforma",
            config={
                "name": "plataforma",
                "colors": {"primary": "#0066cc"},
                "branding": {"logoAlt": "Gov Gen AI Platform"},
            },
        )
        org = await _organizacion(db_session)
        await _tema(
            db_session,
            name="Institucional",
            organizacion_id=org.id,
            config={"branding": {"logoUrl": "/api/v1/hub/themes/x/logo", "logoAlt": "UJI"}},
        )

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            config = (await cliente.get("/api/v1/hub/themes/resolved")).json()["config"]

        assert config["branding"]["logoAlt"] == "UJI"
        assert config["branding"]["logoUrl"] == "/api/v1/hub/themes/x/logo"
        assert config["colors"]["primary"] == "#0066cc"

    @pytest.mark.asyncio
    async def test_should_not_leak_which_organization_the_theme_belongs_to(self, db_session):
        """Misma disciplina que `get_theme_for_chatbot` (SEC.5): solo `config`. El id o el
        nombre del tema convertirían este endpoint en un censo de organizaciones."""
        org = await _organizacion(db_session, nombre="Diputación de Castellón")
        await _tema(
            db_session,
            name="Tema de la Diputación",
            organizacion_id=org.id,
            config={"branding": {"logoAlt": "Diputación"}},
        )

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/themes/resolved")).json()

        assert set(cuerpo) == {"config"}
        assert "organizacion_id" not in cuerpo["config"]
        assert "Diputación de Castellón" not in _en_texto(cuerpo)
        assert "Tema de la Diputación" not in _en_texto(cuerpo)

    @pytest.mark.asyncio
    async def test_should_not_be_swallowed_by_the_theme_id_route(self, db_session):
        """`/{theme_id}` va después: registrado antes, `resolved` no es un UUID y la
        respuesta sería un 400 de identificador inválido."""
        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.get("/api/v1/hub/themes/resolved")

        assert respuesta.status_code == 200
        assert "inválido" not in respuesta.text

    @pytest.mark.asyncio
    async def test_should_ignore_the_theme_of_an_organization_that_is_not_yours(self, db_session):
        ajena = await _organizacion(db_session, nombre="Ajena")
        await _tema(
            db_session,
            organizacion_id=ajena.id,
            config={"branding": {"logoAlt": "Marca ajena"}},
        )
        propia = await _organizacion(db_session, nombre="Propia")

        async with _cliente(db_session, _principal(organizacion_ids=[propia.id])) as cliente:
            config = (await cliente.get("/api/v1/hub/themes/resolved")).json()["config"]

        assert config.get("branding", {}).get("logoAlt") != "Marca ajena"


# ───────────────────────── El logotipo va al almacén ─────────────────────────


class TestElLogotipoSeSubePorStorageService:

    @pytest.mark.asyncio
    async def test_should_store_the_logo_and_point_the_url_at_the_api(self, db_session):
        """La regla de portabilidad: el fichero va por `StorageService`, no al disco. Y la
        URL apunta al endpoint, no a una ruta del repositorio."""
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})
        almacen = AlmacenFalso()

        async with _cliente(
            db_session, _principal(organizacion_ids=[org.id]), almacen
        ) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
            )

        assert respuesta.status_code == 200, respuesta.text
        assert almacen.objetos[f"branding/{tema.id}/logo"] == PNG
        assert respuesta.json()["logoUrl"] == f"/api/v1/hub/themes/{tema.id}/logo"

    @pytest.mark.asyncio
    async def test_should_record_the_mark_in_the_theme_config(self, db_session):
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
                data={"logoAlt": "Ayuntamiento de Vila-real"},
            )

        await db_session.refresh(tema)
        assert tema.config["branding"]["logoUrl"].endswith(f"/{tema.id}/logo")
        assert tema.config["branding"]["logoAlt"] == "Ayuntamiento de Vila-real"
        assert tema.config["branding"]["logoContentType"] == "image/png"

    @pytest.mark.asyncio
    async def test_should_reject_something_that_is_not_an_image(self, db_session):
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.txt", b"no soy una imagen", "text/plain")},
            )

        assert respuesta.status_code == 415

    @pytest.mark.asyncio
    async def test_should_reject_an_svg_even_when_it_claims_to_be_an_image(self, db_session):
        """Un SVG es un documento con guion dentro. Servido desde el origen de la API,
        subir la marca sería subir código ejecutable a la aplicación."""
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={
                    "file": (
                        "marca.svg",
                        b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
                        "image/svg+xml",
                    )
                },
            )

        assert respuesta.status_code == 415

    @pytest.mark.asyncio
    async def test_should_reject_a_png_extension_with_another_content(self, db_session):
        """El `content_type` del multipart lo elige quien sube: manda la firma real."""
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", b"MZ\x90\x00ejecutable", "image/png")},
            )

        assert respuesta.status_code == 415

    @pytest.mark.asyncio
    async def test_should_reject_a_logo_over_the_limit(self, db_session):
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG + b"x" * (2 * 1024 * 1024), "image/png")},
            )

        assert respuesta.status_code == 413

    @pytest.mark.asyncio
    async def test_should_forbid_an_admin_from_another_organization(self, db_session):
        """SEC.2: aquí la organización sale del tema y no del cuerpo, pero la comprobación
        es la misma — el token dispone."""
        ajena = await _organizacion(db_session, nombre="Ajena")
        tema = await _tema(db_session, organizacion_id=ajena.id, config={"name": "x"})
        propia = await _organizacion(db_session, nombre="Propia")

        async with _cliente(db_session, _principal(organizacion_ids=[propia.id])) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
            )

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_require_superadmin_for_the_platform_mark(self, db_session):
        """La marca de plataforma la hereda todo el mundo: mismo criterio que crear un
        tema de plataforma en `create_theme`."""
        tema = await _tema(db_session, organizacion_id=None, config={"name": "plataforma"})

        async with _cliente(db_session, _principal(role="admin")) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
            )

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_let_a_superadmin_set_the_platform_mark(self, db_session):
        tema = await _tema(db_session, organizacion_id=None, config={"name": "plataforma"})

        async with _cliente(db_session, _principal(role="superadmin")) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
            )

        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_should_refuse_to_brand_a_preset(self, db_session):
        """Los temas `is_default` son la base de estilo que comparten todas las
        organizaciones, igual que en `update_theme`: la marca va en un tema propio, no
        encima de un predefinido."""
        tema = await _tema(
            db_session, organizacion_id=None, is_default=True, config={"name": "default"}
        )

        async with _cliente(db_session, _principal(role="superadmin")) as cliente:
            respuesta = await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
            )

        assert respuesta.status_code == 400


# ───────────────────────── El logotipo se sirve ─────────────────────────


class TestElLogotipoSeSirveComoImagen:

    @pytest.mark.asyncio
    async def test_should_serve_the_bytes_with_their_content_type(self, db_session):
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})
        almacen = AlmacenFalso()

        async with _cliente(
            db_session, _principal(organizacion_ids=[org.id]), almacen
        ) as cliente:
            await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.jpg", JPEG, "image/jpeg")},
            )
            respuesta = await cliente.get(f"/api/v1/hub/themes/{tema.id}/logo")

        assert respuesta.status_code == 200
        assert respuesta.content == JPEG
        assert respuesta.headers["content-type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_should_serve_the_logo_without_an_authorization_header(self, db_session):
        """Un `<img src>` no manda `Authorization`: exigirla convierte la marca en un
        icono roto, y en el widget público no hay sesión ninguna que exigir. El endpoint
        devuelve bytes y nada más, así que no reabre SEC.5."""
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})
        almacen = AlmacenFalso()

        async with _cliente(
            db_session, _principal(organizacion_ids=[org.id]), almacen
        ) as cliente:
            await cliente.post(
                f"/api/v1/hub/themes/{tema.id}/logo",
                files={"file": ("marca.png", PNG, "image/png")},
            )

        # Aplicación montada sin `get_current_user`: si el endpoint lo exigiera, 401.
        async with _cliente(db_session, None, almacen) as anonimo:
            respuesta = await anonimo.get(f"/api/v1/hub/themes/{tema.id}/logo")

        assert respuesta.status_code == 200
        assert respuesta.content == PNG

    @pytest.mark.asyncio
    async def test_should_return_404_when_the_theme_has_no_logo(self, db_session):
        org = await _organizacion(db_session)
        tema = await _tema(db_session, organizacion_id=org.id, config={"name": "x"})

        async with _cliente(db_session, _principal(organizacion_ids=[org.id])) as cliente:
            respuesta = await cliente.get(f"/api/v1/hub/themes/{tema.id}/logo")

        assert respuesta.status_code == 404

    @pytest.mark.asyncio
    async def test_should_return_404_when_the_pointer_survives_but_the_object_does_not(
        self, db_session
    ):
        """El puntero en la configuración y el objeto ausente es el fallo que SEC.8.6
        arregló con los temas en ficheros. Se dice como 404, no como 500."""
        org = await _organizacion(db_session)
        tema = await _tema(
            db_session,
            organizacion_id=org.id,
            config={"branding": {"logoUrl": "/api/v1/hub/themes/x/logo"}},
        )

        async with _cliente(
            db_session, _principal(organizacion_ids=[org.id]), AlmacenFalso()
        ) as cliente:
            respuesta = await cliente.get(f"/api/v1/hub/themes/{tema.id}/logo")

        assert respuesta.status_code == 404


class TestLaMarcaSigueALaOrganizacionElegida:
    """REV.12 — un superadministrador ve la marca de la organización que está mirando.

    El usuario configuró el logotipo y los colores de la UJI y **no los veía**, y preguntó si
    tenía que reiniciar. No: la cascada funde el nivel de organización **sólo cuando quien
    pregunta pertenece a una sola**, y en un superadministrador la lista vacía significa
    «todas», así que responde con la marca de plataforma. Estaba escrito y era razonado — con
    varias organizaciones no había forma de saber cuál es «su casa».

    Lo que ha cambiado es que ahora sí la hay: REV.10 puso una organización elegida en la
    cabecera, y el endpoint puede respetarla.
    """

    @pytest.mark.asyncio
    async def test_should_resolve_the_theme_of_the_organisation_asked_for(self, db_session):
        await _tema(
            db_session,
            name="Plataforma",
            config={"name": "plataforma", "branding": {"logoAlt": "Gov Gen AI Platform"}},
        )
        org = await _organizacion(db_session)
        await _tema(
            db_session,
            name="UJI",
            organizacion_id=org.id,
            config={"branding": {"logoUrl": "/api/v1/hub/themes/x/logo", "logoAlt": "UJI"}},
        )

        # Superadministrador: lista vacía, o sea «todas». El rol importa —`_principal` crea un
        # `admin` por omisión—, porque un admin sin organizaciones tiene que recibir 403.
        async with _cliente(
            db_session, _principal(role="superadmin", organizacion_ids=[])
        ) as cliente:
            config = (
                await cliente.get(f"/api/v1/hub/themes/resolved?organizacion={org.id}")
            ).json()["config"]

        assert config["branding"]["logoAlt"] == "UJI"
        assert config["branding"]["logoUrl"]

    @pytest.mark.asyncio
    async def test_should_keep_answering_the_platform_mark_without_the_parameter(
        self, db_session
    ):
        """Sin parámetro, el comportamiento de hoy: es lo que consume el widget y el panel de
        quien no ha elegido nada todavía."""
        await _tema(
            db_session,
            name="Plataforma",
            config={"name": "plataforma", "branding": {"logoAlt": "Gov Gen AI Platform"}},
        )
        org = await _organizacion(db_session)
        await _tema(
            db_session,
            name="UJI",
            organizacion_id=org.id,
            config={"branding": {"logoAlt": "UJI"}},
        )

        async with _cliente(
            db_session, _principal(role="superadmin", organizacion_ids=[])
        ) as cliente:
            config = (await cliente.get("/api/v1/hub/themes/resolved")).json()["config"]

        assert config["branding"]["logoAlt"] == "Gov Gen AI Platform"

    @pytest.mark.asyncio
    async def test_should_refuse_an_organisation_the_caller_cannot_see(self, db_session):
        """**El test del prompt.** Un admin que pide otra organización recibe 403, **no** la
        marca de plataforma. Devolver algo distinto de lo pedido esconde el fallo de permisos:
        parecería que esa organización no tiene marca, cuando lo que pasa es que no puede
        mirarla."""
        ajena = await _organizacion(db_session)
        propia = await _organizacion(db_session)

        async with _cliente(
            db_session, _principal(organizacion_ids=[propia.id])
        ) as cliente:
            respuesta = await cliente.get(
                f"/api/v1/hub/themes/resolved?organizacion={ajena.id}"
            )

        assert respuesta.status_code == 403, respuesta.text

    @pytest.mark.asyncio
    async def test_should_let_an_admin_ask_for_its_own_organisation(self, db_session):
        propia = await _organizacion(db_session)
        await _tema(
            db_session,
            name="Propia",
            organizacion_id=propia.id,
            config={"branding": {"logoAlt": "La mía"}},
        )

        async with _cliente(
            db_session, _principal(organizacion_ids=[propia.id])
        ) as cliente:
            respuesta = await cliente.get(
                f"/api/v1/hub/themes/resolved?organizacion={propia.id}"
            )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["config"]["branding"]["logoAlt"] == "La mía"


class TestElLogoSeSirveComoLoQueEs:
    """El tipo con el que se sirve el logo sale de sus bytes, no de la configuración del tema.

    `branding.logoContentType` se aceptaba del cuerpo de la edición del tema y se usaba como
    tipo de la respuesta de un endpoint **sin autenticación**: un PNG con HTML detrás servido
    como `text/html` desde el origen de la API.
    """

    async def test_should_serve_a_png_as_png_whatever_the_config_says(self, db_session):
        tema = await _tema(
            db_session,
            config={"branding": {"logoUrl": "/api/v1/hub/themes/x/logo", "logoContentType": "text/html"}},
        )
        almacen = AlmacenFalso()
        almacen.objetos[f"branding/{tema.id}/logo"] = PNG

        async with _cliente(db_session, None, almacen) as cliente:
            respuesta = await cliente.get(f"/api/v1/hub/themes/{tema.id}/logo")

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == "image/png"

    async def test_should_not_serve_what_is_not_an_image(self, db_session):
        tema = await _tema(
            db_session,
            config={"branding": {"logoUrl": "/api/v1/hub/themes/x/logo", "logoContentType": "image/png"}},
        )
        almacen = AlmacenFalso()
        almacen.objetos[f"branding/{tema.id}/logo"] = b"<html><script>alert(1)</script></html>"

        async with _cliente(db_session, None, almacen) as cliente:
            respuesta = await cliente.get(f"/api/v1/hub/themes/{tema.id}/logo")

        assert respuesta.status_code == 404
