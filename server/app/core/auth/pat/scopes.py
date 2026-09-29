"""Catálogo de scopes de PAT y techo de scopes por rol (AUTH.3)."""

from server.app.core.auth.models import UserRole

# Scopes de recurso que un PAT puede portar.
REDACCION_TEMPLATES_READ = "redaccion:templates:read"
REDACCION_TEMPLATES_WRITE = "redaccion:templates:write"
CHATBOTS_READ = "chatbots:read"
CHATBOTS_WRITE = "chatbots:write"
CHAT_TEST = "chat:test"
# RAG.11: inspeccionar el prompt final sin invocar al modelo. Separado de `chat:test`
# porque enseña el system prompt entero y la configuración resuelta del chatbot, que es
# más de lo que concede poder charlar con él.
CHAT_DEBUG = "chat:debug"
# SEC.2.1: habilita la cabecera `X-GovGenAI-Actor`, o sea preguntar en nombre de otra
# persona. Es lo más que concede un PAT, así que va aparte de `chat:test`: sin este scope la
# cabecera se ignora, y un token robado que no lo lleve no puede suplantar a nadie.
CHAT_ONBEHALF = "chat:onbehalf"
# REG.2: registrar un uso de IA ocurrido fuera de la plataforma. Es append-only de metadatos
# —no muta nada— y por eso no se reserva a superadmin como `chatbots:write`.
ACTIVIDAD_WRITE = "actividad:write"
# REG.3: usar la anonimización como servicio. Separado de `actividad:write` porque son dos
# capacidades distintas: una herramienta puede querer limpiar PII sin registrar nada, y otra
# registrar sin pedirnos que le limpiemos texto.
ANONIMIZACION_USE = "anonimizacion:use"
# VAS.1: usar las verificaciones como servicio —contrato de citas, vigencia de un documento y
# auditoria estatica—. **Uno para los tres** y no uno por servicio: son la misma capacidad
# —comprobar con la vara de la plataforma algo que se produjo fuera— y partirlo obligaria a
# pedir tres permisos para un caso de uso. Los tres son de lectura o de computo sin efecto.
VERIFICACIONES_USE = "verificaciones:use"
# FUN.6: ejecutar una función del catálogo por API. **Emisible también por admin**, a diferencia
# de `chatbots:write`: ejecutar una función de la propia organización es una capacidad de la
# organización, y quien la registró ya decidió compartirla dentro del servicio (nivel 2 de la
# Instrucció 02/2026). Lo que sigue reservado a la plataforma es promover una función a nivel 3,
# y eso no se hace con un token.
FUNCIONES_EXECUTE = "funciones:execute"
# AUT.6: depositar el manifiesto de una ejecución hecha fuera. **Aparte de `actividad:write`**
# porque son dos capacidades: registrar que hubo un uso —«quién, qué, cuándo, con qué
# finalidad»— y depositar la evidencia de esa ejecución —modelo, prompt, citas, aprobaciones—.
# Una aplicación puede querer la primera sin la segunda, y un token que sólo anota usos no tiene
# por qué poder escribir evidencia con la que luego se responde en una auditoría.
#
# Lo emite también un admin de organización, como `actividad:write`: es añadir evidencia de lo
# propio, append-only, y no muta nada de la plataforma.
MANIFIESTOS_WRITE = "manifiestos:write"

ALL_SCOPES: frozenset[str] = frozenset(
    {
        REDACCION_TEMPLATES_READ,
        REDACCION_TEMPLATES_WRITE,
        CHATBOTS_READ,
        CHATBOTS_WRITE,
        CHAT_TEST,
        CHAT_DEBUG,
        CHAT_ONBEHALF,
        ACTIVIDAD_WRITE,
        ANONIMIZACION_USE,
        VERIFICACIONES_USE,
        FUNCIONES_EXECUTE,
        MANIFIESTOS_WRITE,
    }
)

# Techo de scopes que cada rol puede EMITIR en un PAT (los demás roles no pueden
# emitir PAT). Un admin queda excluido de `chatbots:write` vía token máquina: la
# mutación in-place de un chatbot en producción es el riesgo dominante (ver
# el análisis previo, valoración 2; procedencia en docs/MCP_SERVER.md §8), así que se reserva a superadmin; el admin sigue
# configurando chatbots de forma interactiva (sesión JWT, no acotada por scopes).
_ROLE_SCOPES: dict[str, frozenset[str]] = {
    UserRole.SUPERADMIN.value: ALL_SCOPES,
    UserRole.ADMIN.value: ALL_SCOPES - {CHATBOTS_WRITE},
}


class UnknownScopeError(ValueError):
    """Se solicitó un scope que no existe en el catálogo."""


def validate_scopes(scopes: list[str]) -> None:
    """Lanza ``UnknownScopeError`` si algún scope no pertenece al catálogo."""
    unknown = [s for s in scopes if s not in ALL_SCOPES]
    if unknown:
        raise UnknownScopeError(f"Unknown scopes: {', '.join(sorted(unknown))}")


def allowed_scopes_for_role(role: str) -> frozenset[str]:
    """Scopes que un rol puede emitir en un PAT (vacío si el rol no puede emitir)."""
    return _ROLE_SCOPES.get(role, frozenset())
