"""Fixtures compartidas para los tests de auth SAML (AUTH.1 / AUTH.2).

Las aserciones SAML firmadas se generan aquí con un par de claves de prueba (sin red,
sin IdP real): se construye la metadata de un IdP de pruebas con su certificado y se
firman respuestas con ``OneLogin_Saml2_Utils.add_sign``. NUNCA se usa el IdP real.

Los tests que tocan BD (``db``) usan el PostgreSQL de desarrollo (localhost:5432) y
limpian las filas creadas en el teardown.
"""

# ── Orden de importación obligatorio, no reordenar ─────────────────────────────
# `langchain_text_splitters` arrastra `sentence_transformers` → torch. En Windows, cargar torch
# DESPUÉS de haber abierto una conexión asyncpg aborta el proceso con «Windows fatal exception:
# access violation»; al revés funciona. Diagnosticado el 2026-07-29. Este fichero crea un motor,
# así que le toca (APER.16).
import langchain_text_splitters  # noqa: F401  ← debe ir primero

import base64
import datetime as dt
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from onelogin.saml2.utils import OneLogin_Saml2_Utils

SP_ENTITY_ID = "https://govgenai.uji.es/sp"
ACS_URL = "http://sp.example.com/api/v1/auth/saml/acs"
IDP_ENTITY_ID = "https://idp.example.com/metadata"
IDP_SSO_URL = "https://idp.example.com/sso"
BASE_URL = "http://sp.example.com"
RETURN_URL = "http://localhost:5173/auth/callback"


# --------------------------------------------------------------------------- #
# Helpers de criptografía / construcción de respuestas SAML firmadas            #
# --------------------------------------------------------------------------- #
def _gen_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test IdP")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, cert_pem


def _cert_body(cert_pem: str) -> str:
    return "".join(
        line for line in cert_pem.splitlines() if "CERTIFICATE" not in line
    ).strip()


def _idp_metadata_xml(cert_pem: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" '
        f'entityID="{IDP_ENTITY_ID}">'
        '<IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<KeyDescriptor use="signing">'
        '<KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#"><X509Data>'
        f"<X509Certificate>{_cert_body(cert_pem)}</X509Certificate>"
        "</X509Data></KeyInfo></KeyDescriptor>"
        '<SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
        f'Location="{IDP_SSO_URL}"/>'
        "</IDPSSODescriptor></EntityDescriptor>"
    )


def _saml_time(offset_seconds: int = 0) -> str:
    return (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _attribute(name: str, *values: str) -> str:
    vals = "".join(f"<saml:AttributeValue>{v}</saml:AttributeValue>" for v in values)
    return f'<saml:Attribute Name="{name}">{vals}</saml:Attribute>'


def _build_signed_response(
    *,
    sign_key_pem: str,
    sign_cert_pem: str,
    email: str = "ada@uji.es",
    audience: str = SP_ENTITY_ID,
    destination: str = ACS_URL,
    not_before_off: int = -300,
    not_after_off: int = 600,
    attributes: dict | None = None,
    in_response_to: str | None = None,
    assertion_id: str = "_assert_id_12345",
) -> str:
    """Construye una Response SAML, firma el root y la devuelve en base64.

    `in_response_to` es el ID del `AuthnRequest` al que contesta: el SP sólo acepta respuestas a
    una petición suya hecha desde el mismo navegador (2026-10-22).
    """
    if attributes is None:
        attributes = {"mail": [email]}
    respuesta_a = f' InResponseTo="{in_response_to}"' if in_response_to else ""
    attr_xml = "".join(_attribute(n, *vs) for n, vs in attributes.items())

    # SEC.8.4: el SP exige ahora `wantAssertionsSigned`, así que la aserción se firma
    # aparte y ya firmada se mete en la Response, que se firma a su vez. Antes solo se
    # firmaba la raíz, que es justo la configuración que el hallazgo señalaba: con binding
    # HTTP-POST la identidad viaja en la aserción, y sin firma propia no se verifica.
    assertion_xml = (
        '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{assertion_id}" Version="2.0" '
        f'IssueInstant="{_saml_time()}">'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        "<saml:Subject>"
        '<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{email}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{_saml_time(not_after_off)}" '
        f'Recipient="{destination}"{respuesta_a}/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f'<saml:Conditions NotBefore="{_saml_time(not_before_off)}" '
        f'NotOnOrAfter="{_saml_time(not_after_off)}">'
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience>"
        "</saml:AudienceRestriction></saml:Conditions>"
        f'<saml:AuthnStatement AuthnInstant="{_saml_time()}" SessionIndex="_sess_idx_1">'
        "<saml:AuthnContext><saml:AuthnContextClassRef>"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
        "</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>"
        f"<saml:AttributeStatement>{attr_xml}</saml:AttributeStatement>"
        "</saml:Assertion>"
    )
    assertion_firmada = _sin_declaracion(
        OneLogin_Saml2_Utils.add_sign(assertion_xml, sign_key_pem, sign_cert_pem)
    )

    xml = (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        'ID="_resp_id_12345" Version="2.0" '
        f'IssueInstant="{_saml_time()}" Destination="{destination}"{respuesta_a}>'
        f"<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>"
        "<samlp:Status><samlp:StatusCode "
        'Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f"{assertion_firmada}</samlp:Response>"
    )
    signed = _sin_declaracion(
        OneLogin_Saml2_Utils.add_sign(xml, sign_key_pem, sign_cert_pem)
    )
    return base64.b64encode(signed.encode("utf-8")).decode("ascii")


def _sin_declaracion(xml) -> str:
    """`add_sign` puede devolver bytes y anteponer la declaración XML; incrustar eso
    dentro de otro documento lo deja mal formado."""
    texto = xml.decode("utf-8") if isinstance(xml, bytes) else xml
    if texto.lstrip().startswith("<?xml"):
        texto = texto.split("?>", 1)[1]
    return texto.strip()


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _base_auth_env(monkeypatch):
    """JWT + TESTING para todos los tests de auth (create_token/decode_token)."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
    monkeypatch.setenv("TESTING", "1")


@pytest.fixture
def saml_ctx(monkeypatch):
    """Configura el entorno SAML con un IdP de pruebas y expone el contexto."""
    key_pem, cert_pem = _gen_keypair()
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")
    monkeypatch.setenv("SAML_ENABLED", "true")
    monkeypatch.setenv("SAML_SP_ENTITY_ID", SP_ENTITY_ID)
    monkeypatch.setenv("SAML_SP_ACS_URL", ACS_URL)
    monkeypatch.setenv("SAML_IDP_METADATA_XML", _idp_metadata_xml(cert_pem))
    monkeypatch.setenv("SAML_ATTR_EMAIL", "mail")
    monkeypatch.setenv("SAML_ATTR_NAME", "displayName")
    monkeypatch.setenv("SAML_ATTR_ROLE", "role")
    monkeypatch.setenv("SAML_ATTR_GROUPS", "groups")
    monkeypatch.setenv("SAML_DEFAULT_ROLE", "user")
    monkeypatch.setenv("SAML_FRONTEND_RETURN_URL", RETURN_URL)
    monkeypatch.delenv("SAML_GROUP_ROLE_MAP", raising=False)

    def _make_response(**kwargs):
        kwargs.setdefault("sign_key_pem", key_pem)
        kwargs.setdefault("sign_cert_pem", cert_pem)
        return _build_signed_response(**kwargs)

    return SimpleNamespace(
        key_pem=key_pem,
        cert_pem=cert_pem,
        sp_entity_id=SP_ENTITY_ID,
        acs_url=ACS_URL,
        idp_entity_id=IDP_ENTITY_ID,
        idp_sso_url=IDP_SSO_URL,
        base_url=BASE_URL,
        return_url=RETURN_URL,
        idp_metadata_xml=_idp_metadata_xml(cert_pem),
        make_response=_make_response,
        gen_keypair=_gen_keypair,
    )


@pytest.fixture
async def db(db_url):
    """Sesión contra la BD desechable del test (fixture `db_url` del conftest raíz).

    La versión anterior apuntaba al PostgreSQL de desarrollo y limpiaba por email en el
    teardown (TST.2): ahora la BD entera se borra al acabar el test, así que la
    limpieza sobra. Se conserva ``track(email)`` como no-op para no tocar los tests.

    Las tablas del hub ya vienen creadas por `db_url`; aquí se añaden las de SQLModel
    (SuperAdminAccount, AdminAccount…), que los tests de auth también usan.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    # Importar los modelos ANTES del `create_all`, y no dentro de cada test. `SQLModel.metadata`
    # solo conoce las tablas de los módulos que ya se han importado, así que sin esto el
    # `create_all` de abajo no creaba nada cuando este fichero era el primero de la sesión:
    # el test moría con `UndefinedTableError: relation "superadminaccount" does not exist` y el
    # fallo parecía de la lógica que estuviera probando. Funcionaba por casualidad, porque otro
    # módulo de test importaba los modelos antes.
    import server.app.database.models  # noqa: F401

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session = AsyncSession(engine)
    tracked: list[str] = []

    ns = SimpleNamespace(
        session=session, engine=engine, track=tracked.append, emails=tracked
    )
    try:
        yield ns
    finally:
        await session.close()
        await engine.dispose()
