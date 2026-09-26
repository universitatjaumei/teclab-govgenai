"""LANG — `val` y `ca` son la misma lengua: el corpus la escribe `val`

Revision ID: a1c2v3l4m5n6
Revises: 96acb5e218ec
Create Date: 2026-09-26

El corpus llama `val` al valenciano —lo fija `docs/CONTRATO_MD_CORPUS.md`— y `langdetect` lo
llama `ca`. ACT.2 cerró el desajuste en la detección, que es la puerta por la que entra la lengua
de la *pregunta*. Los documentos entran por otra, y los que se ingirieron antes de aquello se
quedaron con el código que ya no usa nadie más.

**Qué rompe tener los dos códigos vivos.** No es un error visible: el documento existe y se
recupera. Lo que hace es (1) ordenarse detrás de todo en `prefer`, que compara la lengua del
documento con la de la pregunta, y (2) **disparar el aviso de traducción contra una pregunta en
valencià**, o sea decirle a quien escribe en su lengua que la norma citada está en otra. Es el
mismo defecto que ACT.2 describió al revés.

**Por qué normalizar hacia `val` y no al contrario.** `val` es el código que llevan escrito los
`.md` del corpus y su contrato. Ir al revés costaría reescribir los documentos y reindexar; ir
hacia aquí cuesta este `UPDATE`.

**Qué NO toca.** `hub_prompt_templates.language`, que es otro eje —cuál de las variantes de un
prompt se usa, no en qué lengua está una norma— y cuyo `UniqueConstraint(chatbot_id, slug,
language)` puede chocar si existieran las dos variantes. Su módulo no tiene hoy importador vivo
(issue #153) y normalizarlo a ciegas cambiaría filas que nadie lee, arriesgando una colisión a
cambio de nada.

`hub_document_chunks.tsv` es una columna generada a partir de `language`, así que se recalcula
sola. El resultado es idéntico: la configuración de texto es `simple` para todo lo que no sea
`es`, y ni `ca` ni `val` lo son.
"""
from alembic import op

revision = "a1c2v3l4m5n6"
down_revision = "96acb5e218ec"
branch_labels = None
depends_on = None

#: Las tablas con una columna `language` que describe **la lengua de un texto del corpus**.
#: Las cuatro son operacionales: la configuración no guarda lenguas de documentos.
TABLAS = (
    "hub_documents",
    "hub_document_chunks",
    "hub_crawled_pages",
    "hub_ingestion_jobs",
)


def upgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"UPDATE {tabla} SET language = 'val' WHERE language = 'ca'")


def downgrade() -> None:
    """No hay vuelta atrás, y decirlo es más honesto que fingirla.

    Después de este `UPDATE` no queda ninguna manera de distinguir qué filas llevaban `ca` y
    cuáles llevaban `val`: son la misma lengua y ese era el punto. Un `downgrade` que las
    devolviera todas a `ca` no restauraría el estado anterior, lo inventaría — y dejaría en `ca`
    los 511 documentos que nunca lo estuvieron.
    """
    pass
