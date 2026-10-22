"""Construcción de la configuración de python3-saml desde el entorno.

El IdP se resuelve a partir de su metadata (XML inline en ``SAML_IDP_METADATA_XML`` o
remota en ``SAML_IDP_METADATA_URL``). En despliegue institucional se apunta a la metadata
real de la UJI; en desarrollo/tests se usa un IdP de pruebas vía XML inline.
"""

from onelogin.saml2.constants import OneLogin_Saml2_Constants
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser

from server.app.core.config import get_settings


class InvalidSamlConfigError(Exception):
    """La configuración SAML es incompleta o inválida."""


def _build_sp_settings() -> dict:
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("SAML_SP_ENTITY_ID", settings.saml_sp_entity_id),
            ("SAML_SP_ACS_URL", settings.saml_sp_acs_url),
        )
        if not value
    ]
    if missing:
        raise InvalidSamlConfigError(
            f"Missing required SAML SP config: {', '.join(missing)}"
        )

    sp: dict = {
        "entityId": settings.saml_sp_entity_id,
        "assertionConsumerService": {
            "url": settings.saml_sp_acs_url,
            "binding": OneLogin_Saml2_Constants.BINDING_HTTP_POST,
        },
        "NameIDFormat": OneLogin_Saml2_Constants.NAMEID_EMAIL_ADDRESS,
        "x509cert": settings.saml_sp_x509_cert,
        "privateKey": settings.saml_sp_private_key,
    }
    if settings.saml_sp_sls_url:
        sp["singleLogoutService"] = {
            "url": settings.saml_sp_sls_url,
            "binding": OneLogin_Saml2_Constants.BINDING_HTTP_REDIRECT,
        }
    return sp


def _security_settings() -> dict:
    # SEC.8.4: con binding HTTP-POST la aserción viaja dentro de la respuesta, así que
    # exigir firma solo en el mensaje deja sin verificar la pieza que porta la identidad.
    # Y aceptar respuestas no solicitadas —sin `InResponseTo` que casar con una petición
    # nuestra— convierte una aserción capturada en reutilizable.
    #
    # **Este ajuste solo no lo impide**, y el comentario de arriba lo daba por hecho hasta el
    # 2026-10-22: python3-saml sólo compara `InResponseTo` si se le pasa el ID de la petición, y
    # el ACS no se lo pasaba. Lo cierran `saml_auth_router`: el ID va en una cookie desde
    # `/login`, el ACS exige que la respuesta conteste a él y recuerda las aserciones usadas.
    return {
        "wantMessagesSigned": True,
        "wantAssertionsSigned": True,
        "requestedAuthnContext": False,
        "rejectUnsolicitedResponsesWithInResponseTo": True,
    }


def build_saml_settings(*, sp_only: bool = False) -> dict:
    """Devuelve el dict de configuración para OneLogin_Saml2_Auth/Settings.

    Si ``sp_only`` es ``True`` se omite el IdP (sirve para generar la metadata del SP,
    que no necesita el IdP). En otro caso, se exige y se mezcla la metadata del IdP.
    """
    settings = get_settings()
    if not settings.saml_enabled:
        raise InvalidSamlConfigError("SAML SSO is not enabled (SAML_ENABLED=false)")

    base: dict = {
        "strict": True,
        "debug": settings.is_dev_mode,
        "sp": _build_sp_settings(),
        "security": _security_settings(),
    }

    if sp_only:
        return base

    if settings.saml_idp_metadata_xml:
        idp_data = OneLogin_Saml2_IdPMetadataParser.parse(
            settings.saml_idp_metadata_xml
        )
    elif settings.saml_idp_metadata_url:
        # SEC.8.4: la metadata trae el certificado con el que se verifican TODAS las
        # aserciones. Descargarla sin validar TLS deja que un intermediario sustituya esa
        # clave y firme identidades a su gusto; el resto de la cadena seguiría cuadrando.
        idp_data = OneLogin_Saml2_IdPMetadataParser.parse_remote(
            settings.saml_idp_metadata_url, validate_cert=True
        )
    else:
        raise InvalidSamlConfigError(
            "Missing IdP metadata: set SAML_IDP_METADATA_XML or SAML_IDP_METADATA_URL"
        )

    if not idp_data.get("idp", {}).get("entityId"):
        raise InvalidSamlConfigError("IdP metadata did not yield a valid entityId")

    return OneLogin_Saml2_IdPMetadataParser.merge_settings(base, idp_data)
