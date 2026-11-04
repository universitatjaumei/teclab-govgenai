"""Adaptador entre el modelo y el nodo de redacción del grafo (VER.1). Deploy: edge.

`AIAssistDraftNode` invoca `llm.generate(prompt=<ai_prompt_template_id>, context=...)`, y ese
`prompt` **no es un prompt**: es el identificador de una plantilla. En el módulo de redacción
no había nada que lo resolviera —`hub_prompt_templates` cuelga de un chatbot y es otra
cosa—, así que cablear el modelo sin resolverlo sería pedirle que redacte un informe con la
instrucción «generic_report_v1».

El catálogo vive aquí, como dato del módulo, y es deliberadamente pequeño: hoy los perfiles
solo declaran un identificador. Cuando haya que editarlos desde el panel, esto es lo que se
sustituye por una tabla, sin tocar el grafo.
"""
from __future__ import annotations

from typing import Any

from server.app.core.llm_text import texto_de

#: El prompt de sistema por omisión.
#:
#: **AIS.2 — decía «de una universidad pública»**, y el destinatario declarado del proyecto son
#: varias administraciones y en particular **entidades locales**: un ayuntamiento que generara un
#: informe recibía texto que le decía al modelo que es una universidad. «Administración pública»
#: cubre a las dos sin presumir de cuál se trata, que es lo que pide `CONTRIBUTING.md`.
SISTEMA_POR_DEFECTO = (
    "Eres un redactor de informes institucionales de una administración pública. Redactas en "
    "la lengua del contexto que se te da. Te apoyas ÚNICAMENTE en los datos del contexto: "
    "no añades cifras, fechas ni nombres que no aparezcan en él, y si un dato falta lo dices "
    "en vez de inventarlo. El tono es sobrio y administrativo, sin adjetivos valorativos."
)

#: Identificadores estables: van al bloque como `prompt_version` y al manifiesto, así que
#: **no se renombran** sin asumir que los informes ya generados dejan de ser reconstruibles.
PROMPT_VALORACION_DE_TENDENCIA = "valoracion_de_tendencia_v1"
PROMPT_RESUMEN_DE_RESULTADOS = "resumen_de_resultados_v1"


# SEG.2 — las reglas de las dos instrucciones siguientes se portan del prompt que el usuario ya
# usaba con una gema de Gemini. Allí iban en mayúsculas porque era lo único que había para
# defenderlas; cada una viene de un fallo observado —tablas inventadas, resúmenes que omitían—
# y no de una preferencia de estilo.
#: AIS.2 — público, porque el catálogo de actividades lo importa para poder sobreescribirlo.
#: El texto se queda aquí, donde lo escribió SEG.2 con sus razones al lado, en vez de moverse:
#: cada una de sus reglas viene de un fallo observado y no de una preferencia de estilo.
PROMPT_TEXTO_VALORACION = _VALORACION_DE_TENDENCIA = (
    "Valora la evolución de los indicadores de la tabla del contexto, comparando el último "
    "curso o ejercicio con los anteriores.\n"
    "\n"
    "Reglas, y son duras:\n"
    "- Apóyate ÚNICAMENTE en las cifras de esta tabla. Un dato que no esté en ella no se "
    "menciona, ni siquiera si lo sabes por otra vía.\n"
    "- **No calcules** nada que no venga dado: ni medias, ni totales, ni porcentajes, ni "
    "agregados. Si una cifra que haría falta no está, dilo.\n"
    "- Una celda sin dato —«No hay valor», vacía o equivalente— es una AUSENCIA: se dice que "
    "ese curso no tiene medición y no se rellena, ni se interpola, ni se sustituye por cero. "
    "La diferencia entre «no hay dato» y «el dato es cero» es información.\n"
    "- Di si la tendencia de cada indicador crece, decrece o se mantiene, con las cifras "
    "delante.\n"
    "- Cuando un indicador empeore, puedes sugerir acciones de mejora, pero **no uses "
    "imperativos**: son sugerencias para que quien firma el informe las considere, con tono "
    "neutro y sin atribuir responsabilidades.\n"
    "- Si observas una relación entre dos variables de la misma tabla, puedes señalarla "
    "marcándola explícitamente como hipótesis, nunca como causa demostrada.\n"
    "- Cierra dejando claro que la reflexión cualitativa corresponde a quien firma el informe.\n"
    "\n"
    # SEG.5 — las dos reglas de forma salen de leer el informe montado con las nueve tablas
    # reales: el modelo devolvía un ensayo por tabla, con sus propios apartados, y con markdown
    # que el informe imprimía literalmente («**Producción vegetal:**»).
    "Forma del texto, y también son reglas:\n"
    "- Escribe **prosa corrida**, uno o dos párrafos cortos. Es un apartado de un informe, no "
    "un análisis independiente: nadie va a leer nueve ensayos seguidos.\n"
    "- Sin markdown: ni asteriscos, ni almohadillas, ni viñetas, ni negritas, ni apartados con "
    "título propio. El informe imprime tu texto tal cual, así que un asterisco sale impreso.\n"
    "\n"
    "No reproduzcas la tabla: ya está en el informe. Interprétala."
)

PROMPT_TEXTO_RESUMEN = _RESUMEN_DE_RESULTADOS = (
    "Resume los resultados que muestran las tablas del contexto, que pueden ser varias tablas "
    "de un mismo apartado.\n"
    "\n"
    "Reglas, y son las mismas de siempre:\n"
    "- Cada afirmación se apoya en una cifra de las tablas, y sólo en ellas.\n"
    "- **No calcules** agregados que no vengan dados, ni compares magnitudes que midan cosas "
    "distintas.\n"
    "- Una celda sin dato —«No hay valor»— es una ausencia y se dice; no se rellena.\n"
    "- Menciona TODAS las tablas del contexto: si una no aporta nada al resumen, dilo en una "
    "frase en vez de omitirla en silencio. Dejar fuera una tabla sin avisar es el fallo más "
    "difícil de detectar de un resumen.\n"
    "- Sin conclusiones que las cifras no sostengan, y sin adjetivos valorativos.\n"
    "\n"
    "Forma del texto, y también son reglas:\n"
    "- Escribe **prosa corrida**, dos o tres párrafos cortos como máximo.\n"
    "- Sin markdown: ni asteriscos, ni almohadillas, ni viñetas, ni negritas, ni apartados con "
    "título propio. El informe imprime tu texto tal cual.\n"
    "\n"
    "Cierra dejando claro que la valoración cualitativa corresponde a quien firma el informe."
)


CATALOGO_DE_PROMPTS: dict[str, str] = {
    "generic_report_v1": (
        "Redacta esta sección del informe a partir de los datos extraídos que figuran en el "
        "contexto. Empieza por lo que responde a la finalidad de la sección, apoya cada "
        "afirmación en un dato del contexto y cierra sin conclusiones que los datos no "
        "sostengan. No repitas las tablas: interprétalas."
    ),
    PROMPT_VALORACION_DE_TENDENCIA: _VALORACION_DE_TENDENCIA,
    PROMPT_RESUMEN_DE_RESULTADOS: _RESUMEN_DE_RESULTADOS,
}

_SIN_CATALOGO = (
    "Redacta esta sección del informe a partir de los datos del contexto, apoyando cada "
    "afirmación en uno de ellos. La plantilla de prompt «{prompt_id}» no está en el catálogo "
    "del módulo, así que se usa la instrucción genérica."
)


def instruccion_para(prompt_id: str) -> str:
    """La instrucción real que corresponde a un `ai_prompt_template_id`.

    Cuando el identificador no está en el catálogo **viaja dentro de la instrucción** en vez
    de desaparecer: es lo único que permite saber después qué plantilla pidió esa redacción,
    y deja el hueco a la vista en lugar de degradarse en silencio.
    """
    if prompt_id in CATALOGO_DE_PROMPTS:
        return CATALOGO_DE_PROMPTS[prompt_id]
    return _SIN_CATALOGO.format(prompt_id=prompt_id)


class RedactorDeBloques:
    """Implementa el protocolo `LLMService` que espera `AIAssistDraftNode`.

    `model_name` no es decorativo: el nodo lo guarda en el bloque como `model_used`, y es lo
    que permite saber con qué modelo se redactó un informe meses después.

    **AIS.2 — `instrucciones` y `sistema` entran por el constructor.** Antes la instrucción salía
    de un `dict` de este módulo y el prompt de sistema era una constante, así que los dos prompts
    de redacción eran los únicos del módulo que **no se podían afinar sin desplegar**: el
    mecanismo de MT.6 existía y a estos no llegaba. Se resuelven donde hay sesión y organización
    —`workspaces_router`— y se entregan ya resueltos, para que `generate` siga sin tocar la base
    de datos: es un método que corre dentro de un nodo del grafo.

    Los valores por omisión mantienen el comportamiento de antes, que es lo que permite que los
    tests del grafo construyan un redactor con dos argumentos.

    **`modelos`: un modelo por instrucción.** La valoración y el resumen son actividades
    distintas y la biblioteca de prompts puede ponerlas en niveles distintos; con un solo modelo,
    subir el nivel de una no llegaba a ninguna parte. Lo que no está en `modelos` —la instrucción
    genérica o un identificador fuera del catálogo— usa `modelo`.
    """

    def __init__(
        self,
        modelo: Any,
        model_name: str,
        *,
        sistema: str | None = None,
        instrucciones: dict[str, str] | None = None,
        modelos: dict[str, tuple[Any, str]] | None = None,
    ) -> None:
        self._modelo = modelo
        self.model_name = model_name
        self._sistema = sistema or SISTEMA_POR_DEFECTO
        self._instrucciones = instrucciones or {}
        self._modelos = modelos or {}

    def _modelo_para(self, prompt_id: str) -> tuple[Any, str]:
        """El modelo que redacta esa instrucción y su nombre, sacados de un único sitio: así
        `generate` no puede redactar con uno mientras `model_used` registra otro."""
        return self._modelos.get(prompt_id, (self._modelo, self.model_name))

    def nombre_del_modelo_para(self, prompt_id: str) -> str:
        """El modelo que redacta esa instrucción: es lo que el nodo guarda como `model_used`."""
        return self._modelo_para(prompt_id)[1]

    def instruccion(self, prompt_id: str) -> str:
        """La instrucción que se va a usar: la resuelta si la hay, y si no la del catálogo.

        Un override en blanco **no** gana: `resolver_actividad` ya devuelve el texto del código
        cuando la fila está vacía, y repetir aquí la comprobación evita que un `dict` construido
        a mano en otro sitio deje al modelo sin instrucción.
        """
        propia = self._instrucciones.get(prompt_id)
        if propia and propia.strip():
            return propia
        return instruccion_para(prompt_id)

    async def generate(self, prompt: str, context: str) -> str:
        modelo, _ = self._modelo_para(prompt)
        respuesta = await modelo.ainvoke([
            {"role": "system", "content": self._sistema},
            {
                "role": "user",
                "content": (
                    f"{self.instruccion(prompt)}\n\n"
                    f"--- DATOS EXTRAÍDOS ---\n{context}"
                ),
            },
        ])
        return texto_de(respuesta)
