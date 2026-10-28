"""Qué modos de recuperación buscan por fragmentos. Sin dependencias, a propósito (#298).

Lo leen el watcher, el recalculador del corpus y el router cloud de chatbots. Vivió en el watcher
—y el router cloud tenía que importar la ingesta para leer dos cadenas— y luego en
`public_graphs/validacion.py`, que arrastra los registros de perfiles y estrategias: la revisión
de la PR #314 vio que importar el watcher cargaba así cientos de módulos para nada.
"""
from __future__ import annotations

#: ACT.8 — modos de recuperacion que CONSULTAN el indice vectorial, y por tanto necesitan que
#: sus documentos esten troceados y embebidos.
#:
#: Aqui ponia `== "RAG"`, y la premisa —«los otros dos modos no embeben nada»— estaba escrita
#: igual en tres sitios. Fue una decision, pero es ANTERIOR a que el agentico tuviera busqueda
#: por fragmentos: `MD_AGENT_SELECTOR` expone `search_knowledge`, que embebe la consulta y llama
#: a `hybrid_search`, y el bloque HIB reparo sus 14.198 fragmentos dejando escrito que «no son
#: peso muerto». Al actualizar el corpus el 28-08-2026 sus 6 documentos nuevos entraron sin un
#: solo fragmento, y el informe decia `ingeridos=6` sin mentir: el documento si entro.
#:
#: Y habia un defecto latente peor que el hueco: la rama que no trocea BORRA los fragmentos que
#: hubiera, asi que reingerir un documento del agentico se los llevaba. Se habria ido vaciando
#: pasada a pasada sin que nada avisara.
#:
#: `MD_LONG_CONTEXT` no esta, y es correcto: inyecta documentos enteros y no consulta el indice
#: nunca, asi que alli los fragmentos si son peso muerto y borrarlos es lo que toca.
MODOS_QUE_BUSCAN_POR_FRAGMENTOS = ("RAG", "MD_AGENT_SELECTOR")
