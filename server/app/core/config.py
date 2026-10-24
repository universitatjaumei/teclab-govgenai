"""
Server core configuration.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_expiration_minutes: int
    environment: str
    # Sandbox (script-sandbox microservice — SBX.1/SBX.2)
    sandbox_base_url: str = "http://script-sandbox:5000"
    sandbox_timeout_seconds_default: int = 30
    sandbox_connect_timeout_seconds: float = 5.0
    sandbox_max_retries_on_connect_error: int = 1
    sandbox_mode: str = "http"
    # Content quality scheduler (9Q.5)
    content_quality_enabled: bool = True
    content_quality_interval_hours: int = 24
    content_quality_semantic_enabled: bool = True
    # Cortesía del rastreo (RAS.1) — quien vea el tráfico en sus registros tiene que poder
    # saber quién es y a quién escribir. Va en el User-Agent de cada petición.
    crawler_contact: str = ""
    # APER.1 — la válvula que permite rastrear direcciones de la red privada. Existe porque
    # verificar curación sin salir a internet se hace con un `http.server` en 127.0.0.1, que es
    # justo lo que el guardia bloquea; sin una forma declarada de permitirlo, el guardia se
    # acabaría apagando entero. En producción **impide arrancar** (ver el gate de abajo).
    crawler_allow_private_targets: bool = False
    # SSO SAML (AUTH.1) — Service Provider genérico SAML 2.0
    saml_enabled: bool = False
    saml_sp_entity_id: str = ""
    saml_sp_acs_url: str = ""
    saml_sp_sls_url: str = ""
    saml_sp_x509_cert: str = ""
    saml_sp_private_key: str = ""
    saml_idp_metadata_url: str = ""
    saml_idp_metadata_xml: str = ""
    saml_attr_email: str = "mail"
    saml_attr_name: str = "displayName"
    saml_attr_role: str = "role"
    saml_attr_groups: str = "groups"
    saml_group_role_map: str = ""
    saml_default_role: str = "user"
    saml_frontend_return_url: str = ""
    # SEC.2.1: la organización a la que pertenece este IdP. Sale de aquí y NUNCA de la
    # aserción: si viniera de fuera, quien controla el IdP podría declarar a qué
    # organización pertenece cada persona que entra.
    saml_organizacion_id: str = ""
    # IDE.1 — quién manda sobre el ROL de una persona: `app` o `idp`.
    #
    # Con `app` (defecto) el atributo de rol de la aserción **no se lee**, y tampoco
    # `SAML_GROUP_ROLE_MAP`: quien llega nuevo entra con `SAML_DEFAULT_ROLE` y promocionarlo es
    # un acto de una persona. Con `idp` el rol se resuelve de la aserción en cada entrada, que
    # es el comportamiento anterior a IDE.1 y el modo para el día que el ERP sea la fuente.
    #
    # **No gobierna los grupos ni la organización, a propósito.** Los grupos no se guardan: se
    # leen de cada aserción, así que ahí el IdP es la autoridad por construcción, y son los que
    # repartirán módulos (IDE.5). Y `organizacion_id` sale de `SAML_ORGANIZACION_ID`, o sea de
    # la configuración del despliegue: nunca vino de la aserción, así que no hay autoridad que
    # disputar. Por eso el ajuste se llama `..._ROLE_...` y no `IDENTITY_AUTHORITY` a secas.
    identity_role_authority: str = "app"
    # USR.2 — el login local de una persona (`POST /auth/user/login`), que existe **porque el
    # IdP institucional no está configurado y eso no tiene fecha**: los probadores del piloto
    # tienen que poder entrar como ellos mismos.
    #
    # **El interruptor no es adorno: es lo que hace que esto sea provisional de verdad.** Sin
    # él, «hasta que llegue el SSO» se convierte en «para siempre», que es como envejecen los
    # apaños. Con `false` la ruta responde 404 —como si no existiera— y la acción desaparece del
    # panel. El defecto es `true` **ahora**; cuando el SSO esté en marcha, el defecto es lo
    # primero que hay que darle la vuelta.
    local_user_login_enabled: bool = True
    # === Login con la cuenta institucional de Google (OIDC) ===
    #
    # **El dominio es la autorización, no una comodidad.** Sin comprobar `hd` en el servidor,
    # cualquier cuenta de Google del mundo entra: es el fallo clásico de esta integración. Y va
    # en el servidor **aunque** la pantalla de consentimiento esté en «Interna», porque eso es
    # configuración de una consola que alguien puede cambiar, y una decisión de autorización no
    # se delega a una casilla. Sin dominio declarado, el login queda apagado.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_allowed_domain: str = ""
    #: La URL de vuelta, **declarada y no derivada de la petición**.
    #:
    #: Google exige que coincida **carácter a carácter** con la registrada en la consola, así que
    #: declararla convierte esa coincidencia en algo estructural en vez de una esperanza.
    #:
    #: Y derivarla aquí **no funcionaría**: esta aplicación no arranca con `--proxy-headers` ni
    #: con `FORWARDED_ALLOW_IPS`, y el defecto de uvicorn sólo confía en `127.0.0.1` mientras
    #: Caddy conecta desde la red de Docker. O sea que `request.url_for()` construiría `http://`
    #: y Google rechaza un `redirect_uri` sin TLS que no sea `localhost`. Es el mismo motivo por
    #: el que el SAML declara `SAML_SP_ACS_URL` en vez de deducirla.
    google_oauth_redirect_uri: str = ""

    @property
    def google_login_enabled(self) -> bool:
        """Las cuatro piezas, o nada. Un login a medio configurar es peor que ninguno."""
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret
            and self.google_oauth_allowed_domain
            and self.google_oauth_redirect_uri
        )
    # Subidas (SEC.6) — límite de tamaño y cuota de documentos por chatbot
    max_upload_mb: int = 10
    max_documents_per_chatbot: int = 0  # 0 = sin límite

    @property
    def is_dev_mode(self) -> bool:
        return self.environment == "development"


def get_settings() -> Settings:
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY environment variable is required")
    # sandbox_mode defaults to "local" when TESTING=1 to avoid Docker dependency in CI.
    default_sandbox_mode = "local" if os.getenv("TESTING") == "1" else "http"
    # APER.3 — el valor por omisión de `ENVIRONMENT` es el **permisivo**: sin él no corre
    # ninguno de los cuatro gates de producción y las semillas crean `admin@example.local` con
    # una contraseña que está escrita en el repositorio. La imagen lo ancla a `production`
    # (`Dockerfile`), así que aquí sólo queda el caso del host — y ahí `development` es lo
    # correcto, pero **no puede ser silencioso**: un despliegue accidentalmente permisivo
    # funciona perfectamente hasta que alguien lo aprovecha.
    if os.getenv("ENVIRONMENT") is None:
        logger.warning(
            "ENVIRONMENT no está declarado: se asume 'development', que NO aplica los gates de "
            "producción (secreto de ejemplo, sandbox local, TESTING, rastreo a la red privada) "
            "y siembra la cuenta de administración de desarrollo. Si esto es un despliegue, "
            "declara ENVIRONMENT=production."
        )

    ajustes = Settings(
        jwt_secret_key=secret,
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_expiration_minutes=int(os.getenv("JWT_EXPIRATION_MINUTES", "60")),
        environment=os.getenv("ENVIRONMENT", "development"),
        sandbox_base_url=os.getenv("SANDBOX_BASE_URL", "http://script-sandbox:5000"),
        sandbox_timeout_seconds_default=int(os.getenv("SANDBOX_TIMEOUT_SECONDS_DEFAULT", "30")),
        sandbox_connect_timeout_seconds=float(os.getenv("SANDBOX_CONNECT_TIMEOUT_SECONDS", "5.0")),
        sandbox_max_retries_on_connect_error=int(
            os.getenv("SANDBOX_MAX_RETRIES_ON_CONNECT_ERROR", "1")
        ),
        sandbox_mode=os.getenv("SANDBOX_MODE", default_sandbox_mode),
        content_quality_enabled=os.getenv("CONTENT_QUALITY_ENABLED", "true").lower() != "false",
        content_quality_interval_hours=int(os.getenv("CONTENT_QUALITY_INTERVAL_HOURS", "24")),
        content_quality_semantic_enabled=os.getenv("CONTENT_QUALITY_SEMANTIC_ENABLED", "true").lower() != "false",
        crawler_contact=os.getenv("CRAWLER_CONTACT", ""),
        crawler_allow_private_targets=os.getenv("CRAWLER_ALLOW_PRIVATE_TARGETS", "")
        .strip()
        .lower()
        == "true",
        saml_enabled=os.getenv("SAML_ENABLED", "false").lower() == "true",
        saml_sp_entity_id=os.getenv("SAML_SP_ENTITY_ID", ""),
        saml_sp_acs_url=os.getenv("SAML_SP_ACS_URL", ""),
        saml_sp_sls_url=os.getenv("SAML_SP_SLS_URL", ""),
        saml_sp_x509_cert=os.getenv("SAML_SP_X509_CERT", ""),
        saml_sp_private_key=os.getenv("SAML_SP_PRIVATE_KEY", ""),
        saml_idp_metadata_url=os.getenv("SAML_IDP_METADATA_URL", ""),
        saml_idp_metadata_xml=os.getenv("SAML_IDP_METADATA_XML", ""),
        saml_attr_email=os.getenv("SAML_ATTR_EMAIL", "mail"),
        saml_attr_name=os.getenv("SAML_ATTR_NAME", "displayName"),
        saml_attr_role=os.getenv("SAML_ATTR_ROLE", "role"),
        saml_attr_groups=os.getenv("SAML_ATTR_GROUPS", "groups"),
        saml_group_role_map=os.getenv("SAML_GROUP_ROLE_MAP", ""),
        saml_default_role=os.getenv("SAML_DEFAULT_ROLE", "user"),
        saml_frontend_return_url=os.getenv("SAML_FRONTEND_RETURN_URL", ""),
        saml_organizacion_id=os.getenv("SAML_ORGANIZACION_ID", ""),
        identity_role_authority=os.getenv("IDENTITY_ROLE_AUTHORITY", "app").strip().lower(),
        local_user_login_enabled=os.getenv("LOCAL_USER_LOGIN_ENABLED", "true").lower()
        == "true",
        google_oauth_client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        google_oauth_client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        google_oauth_allowed_domain=os.getenv("GOOGLE_OAUTH_ALLOWED_DOMAIN", "").strip().lower(),
        google_oauth_redirect_uri=os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip(),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        max_documents_per_chatbot=int(os.getenv("MAX_DOCUMENTS_PER_CHATBOT", "0")),
    )
    _assert_entorno_conocido(ajustes)
    _assert_autoridad_del_rol(ajustes)
    _assert_configuracion_de_produccion(ajustes)
    return ajustes


ENTORNOS = ("development", "production")


def _assert_entorno_conocido(ajustes: Settings) -> None:
    """#269 — las puertas de producción comparan con `production` literal.

    Con `prod` o `staging` se desactivaban todas en silencio: el secreto de ejemplo, el sandbox
    local, `TESTING`, CORS, HSTS y `/docs`. Un valor que no está en la lista no arranca.
    """
    if ajustes.environment not in ENTORNOS:
        raise RuntimeError(
            f"ENVIRONMENT={ajustes.environment!r} no es un valor conocido. Admitidos: "
            f"{', '.join(ENTORNOS)}. Cualquier otro desactivaría en silencio las comprobaciones "
            "de producción, que comparan con `production`."
        )


AUTORIDADES_DEL_ROL = ("app", "idp")


def _assert_autoridad_del_rol(ajustes: Settings) -> None:
    """Un valor que no se entiende no se interpreta: aquí se adivinaría quién reparte permisos.

    Falla **siempre**, no solo en producción como el resto de `_assert_configuracion_de_produccion`:
    un entorno de desarrollo con la autoridad equivocada enseña un comportamiento que no es el
    que va a haber, y eso se descubre tarde.
    """
    if ajustes.identity_role_authority not in AUTORIDADES_DEL_ROL:
        raise RuntimeError(
            f"IDENTITY_ROLE_AUTHORITY={ajustes.identity_role_authority!r} no es un valor "
            f"conocido. Admitidos: {', '.join(AUTORIDADES_DEL_ROL)}. "
            "`app` = el rol lo pone una persona y el atributo de rol del IdP se ignora; "
            "`idp` = el rol se resuelve de la aserción en cada inicio de sesión."
        )


_SECRETOS_DE_EJEMPLO = frozenset({
    "change-me-in-production",
    "changeme",
    "secret",
    "test-secret-key",
})


def _assert_configuracion_de_produccion(ajustes: Settings) -> None:
    """Combinaciones que en producción son un fallo de configuración, no una opción.

    Fallar al arrancar es deliberado: `SANDBOX_MODE=local` no da ningún síntoma visible
    —los scripts se ejecutan y devuelven su resultado— mientras corre en el host del
    servidor, con su red y heredando `os.environ`: `JWT_SECRET_KEY`, `DATABASE_URL` y las
    claves de los proveedores quedan al alcance del script. Un despliegue así funciona
    perfectamente hasta que alguien lo aprovecha.
    """
    if ajustes.environment != "production":
        return

    # SEC.8.4: la variable era obligatoria desde SEC.1, pero nada impedía desplegar con el
    # valor de ejemplo del `.env.example`, que está publicado en el repositorio. Un secreto
    # conocido permite firmar tokens de cualquier rol y organización.
    secreto = ajustes.jwt_secret_key or ""
    if secreto.lower() in _SECRETOS_DE_EJEMPLO or len(secreto) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY no puede ser el valor de ejemplo ni tener menos de 32 "
            "caracteres en producción: con él se firman los tokens de todos los roles."
        )

    if ajustes.sandbox_mode == "local":
        raise RuntimeError(
            "SANDBOX_MODE=local ejecuta los scripts en el host del servidor y les entrega "
            "las variables de entorno del proceso. En producción usa el sandbox aislado "
            "(SANDBOX_MODE=http, servicio script-sandbox)."
        )

    # SEC.9.6 — el gate anterior mira `sandbox_mode`, y `sandbox_client` elige el ejecutor
    # local **también** con `TESTING=1`, sea cual sea el modo. Así que con
    # ENVIRONMENT=production, SANDBOX_MODE=http y TESTING=1 el arranque no protestaba y los
    # scripts corrían en el host: exactamente el escenario que este gate dice evitar, alcanzado
    # por otra puerta.
    if os.getenv("TESTING") == "1":
        raise RuntimeError(
            "TESTING=1 en producción hace que el sandbox use el ejecutor local aunque "
            "SANDBOX_MODE sea 'http', así que los scripts correrían en el host. "
            "Quita TESTING del entorno de producción."
        )

    # APER.1 — la misma forma que los tres de arriba, y por la misma razón: una variable que
    # desactiva una protección no da ningún síntoma mientras nadie la aprovecha. Con ella puesta
    # el rastreador vuelve a poder pedir `169.254.169.254` y los contenedores vecinos, o sea que
    # el hallazgo M1 queda reabierto por configuración.
    if ajustes.crawler_allow_private_targets:
        raise RuntimeError(
            "CRAWLER_ALLOW_PRIVATE_TARGETS=true permite que el rastreador pida direcciones "
            "de la red privada del servidor —el servidor de metadatos de la nube, los "
            "contenedores vecinos—. Es una válvula de desarrollo para el portal de pruebas "
            "local: quítala del entorno de producción."
        )
