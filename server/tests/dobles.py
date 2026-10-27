"""Dobles compartidos: el chatbot que se completa solo y los clientes externos con su firma.

## El chatbot

**El problema que resuelve.** Los tests del chat doblan el chatbot con
`MagicMock(spec=HubChatbot)`, y un `MagicMock` inventa un valor para **cualquier** atributo
que no se le haya declarado. Mientras el endpoint solo leía `id` y `retrieval_mode` eso no
molestaba; desde que las guardas miran el modo de acceso (SEC.2.1), las cuotas (SEC.4) y la
ventana de vigencia (SEC.4.1), cada columna nueva convierte a los dobles en un chatbot con
valores absurdos —un `access_mode` que no existe, un límite de un token, una fecha que es un
mock— y cinco ficheros de tests se ponen en rojo por algo que no es el cambio que se estaba
probando.

Ha pasado tres veces seguidas. La cuarta se evita aquí: en vez de enumerar a mano los
campos, se leen del ORM y se rellena **solo lo que el test no haya declarado**, con el
mismo valor por defecto que tendría una fila recién creada.

## Los clientes externos (#281)

Un `MagicMock()` a pelo acepta **cualquier** llamada, y así un test de Langfuse siguió en verde
mientras el SDK renombraba `score` a `create_score` y producción fallaba en cada valoración. Los
dobles de lo que habla con fuera —el modelo de chat y el almacenamiento— se crean con
`create_autospec` sobre la clase real: un método que no existe, o una llamada con otros
argumentos, es un `AttributeError` o un `TypeError` en el test, no en producción. Los métodos
`async` salen como `AsyncMock` sin declararlo. El cliente HTTP no está aquí porque no se dobla:
los tests usan el `httpx.AsyncClient` de verdad con `respx` o un `MockTransport`.
"""
from __future__ import annotations

from unittest.mock import MagicMock, create_autospec

from langchain_core.language_models import BaseChatModel

from server.app.core.storage import StorageService
from server.app.modules.agents_hub.database.config_models import HubChatbot


def modelo_de_chat():
    """Un modelo de chat de LangChain, que es lo que devuelve `model_factory`."""
    return create_autospec(BaseChatModel, instance=True)


def almacenamiento():
    """El `StorageService` que se inyecta con `get_storage_service`."""
    return create_autospec(StorageService, instance=True)


def _valor_por_defecto(columna):
    """El default declarado en el ORM, o `None` si no hay ninguno.

    Los `default` que son invocables —`uuid4`, `list`, la hora actual— se llaman; los
    escalares se copian tal cual. Un `server_default` no se mira: eso lo pone Postgres y
    aquí no hay Postgres.
    """
    defecto = columna.default
    if defecto is None:
        return None
    argumento = getattr(defecto, "arg", None)
    if callable(argumento):
        try:
            return argumento(None)
        except TypeError:
            return argumento()
    return argumento


def completar_chatbot(doble, **declarados):
    """Rellena el doble con los defaults del ORM y devuelve el propio doble.

    Lo que el test ya haya puesto se respeta: solo se tocan los atributos que siguen siendo
    un `MagicMock`, que es la señal de «esto no lo ha declarado nadie».
    """
    for nombre, valor in declarados.items():
        setattr(doble, nombre, valor)

    for columna in HubChatbot.__table__.columns:
        actual = getattr(doble, columna.name, None)
        if isinstance(actual, MagicMock):
            setattr(doble, columna.name, _valor_por_defecto(columna))

    return doble
