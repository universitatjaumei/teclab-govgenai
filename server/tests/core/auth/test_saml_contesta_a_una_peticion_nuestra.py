"""SAML sólo acepta la respuesta a una petición nuestra, hecha desde este navegador, y una vez.

`saml_acs` llamaba a `process_response()` sin el ID del `AuthnRequest`. python3-saml sólo compara
`InResponseTo` cuando se le pasa ese ID, así que `rejectUnsolicitedResponsesWithInResponseTo`
exigía que el atributo existiera pero no que fuera de una petición nuestra; y no se recordaban las
aserciones ya consumidas, de modo que una capturada valía varias veces hasta su `NotOnOrAfter`.

Ahora `/login` deja el ID de la petición en una cookie, el ACS exige que la respuesta conteste a
esa petición, y una aserción no se acepta dos veces.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

_COOKIE = "govgenai_saml_peticion"


def _app(db_url) -> FastAPI:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from server.app.api.deps import get_session
    from server.app.routers.saml_auth_router import router

    async def _sesion():
        eng = create_async_engine(db_url)
        try:
            async with AsyncSession(eng) as s:
                yield s
        finally:
            await eng.dispose()

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return app


def _empezar(cliente) -> str:
    """El ID de la petición que deja `/login` en la cookie."""
    assert cliente.get("/api/v1/auth/saml/login", follow_redirects=False).status_code == 302
    return cliente.cookies.get(_COOKIE)


def _acs(cliente, respuesta: str):
    return cliente.post("/api/v1/auth/saml/acs", data={"SAMLResponse": respuesta}, follow_redirects=False)


def test_should_answer_our_own_request(saml_ctx, db, db_url):
    cliente = TestClient(_app(db_url), base_url=saml_ctx.base_url)
    peticion = _empezar(cliente)
    assert peticion, "el login no deja el ID de la petición"

    resp = _acs(cliente, saml_ctx.make_response(email=f"a-{uuid.uuid4().hex[:6]}@uji.es", in_response_to=peticion))

    assert resp.status_code == 302, resp.text


def test_should_refuse_an_unsolicited_response(saml_ctx, db, db_url):
    cliente = TestClient(_app(db_url), base_url=saml_ctx.base_url)

    resp = _acs(cliente, saml_ctx.make_response())

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "SAML_NO_SOLICITADA"


def test_should_refuse_an_answer_to_another_request(saml_ctx, db, db_url):
    """La respuesta de un login que empezó otro navegador no sirve en éste."""
    cliente = TestClient(_app(db_url), base_url=saml_ctx.base_url)
    _empezar(cliente)

    resp = _acs(cliente, saml_ctx.make_response(in_response_to="_peticion_de_otro_navegador"))

    assert resp.status_code == 401, resp.text


def test_should_not_accept_the_same_assertion_twice(saml_ctx, db, db_url):
    app = _app(db_url)
    primero = TestClient(app, base_url=saml_ctx.base_url)
    peticion = _empezar(primero)
    respuesta = saml_ctx.make_response(
        email=f"b-{uuid.uuid4().hex[:6]}@uji.es",
        in_response_to=peticion,
        assertion_id=f"_a_{uuid.uuid4().hex}",
    )
    assert _acs(primero, respuesta).status_code == 302

    # Quien la capturó la reenvía con la misma cookie: la petición es la misma, la aserción ya se usó.
    segundo = TestClient(app, base_url=saml_ctx.base_url)
    segundo.cookies.set(_COOKIE, peticion)
    resp = _acs(segundo, respuesta)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "SAML_REUTILIZADA"
