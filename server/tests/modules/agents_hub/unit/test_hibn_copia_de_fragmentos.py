"""HIB.N — lo que protege que copiar fragmentos no rompa la recuperación en silencio.

Copiar entre corpus es la clase de operación que no falla: acaba, dice que sí, y deja la
recuperación mintiendo. Los dos modos de ese fallo tienen aquí un test cada uno — el metadato
`document_id` sin remapear, y un padre que el techo del destino prohíbe.
"""
import uuid

from server.app.modules.agents_hub.ingestion.chunk_copier import (
    incoherentes,
    remapea,
    se_puede_copiar,
)

HASH = "a" * 64


def _fragmento(parent: str = "x" * 400, **cambios) -> dict:
    base = {
        "content": "Article 4. Permanencia en primer curs...",
        "parent_content": parent,
        "chunk_metadata": {"ancora": "art-4", "document_id": str(uuid.uuid4())},
        "document_id": uuid.uuid4(),
        "chatbot_id": uuid.uuid4(),
    }
    base.update(cambios)
    return base


class TestElPermisoDeCopiaSeComprobaSobreLosDatos:

    def test_should_copy_chunks_only_when_hash_strategy_and_cap_match(self):
        v = se_puede_copiar(
            hash_origen=HASH,
            hash_destino=HASH,
            estrategia_destino="parent_child",
            techo_destino=8000,
            fragmentos=[_fragmento(), _fragmento()],
        )
        assert v.copiable
        assert v.motivo is None

    def test_should_refuse_to_copy_a_different_document(self):
        v = se_puede_copiar(
            hash_origen=HASH,
            hash_destino="b" * 64,
            estrategia_destino="parent_child",
            techo_destino=8000,
            fragmentos=[_fragmento()],
        )
        assert not v.copiable
        assert "content_hash" in v.motivo

    def test_should_refuse_to_copy_when_the_chunking_strategy_differs(self):
        """El origen sin padre y el destino con `parent_child`: copiar dejaría el small-to-big
        sin la sección entera, que es exactamente lo que ese troceado existe para dar."""
        v = se_puede_copiar(
            hash_origen=HASH,
            hash_destino=HASH,
            estrategia_destino="parent_child",
            techo_destino=8000,
            fragmentos=[_fragmento(parent=""), _fragmento(parent="")],
        )
        assert not v.copiable
        assert "parent_child" in v.motivo

        # Y al revés: el destino `structural` no debe recibir padres.
        v2 = se_puede_copiar(
            hash_origen=HASH,
            hash_destino=HASH,
            estrategia_destino="structural",
            techo_destino=8000,
            fragmentos=[_fragmento()],
        )
        assert not v2.copiable
        assert "structural" in v2.motivo

    def test_should_refuse_a_parent_above_the_target_cap(self):
        """El caso real del 2026-08-27: los fragmentos de Normativa se crearon antes de que
        HIB.L fijara el techo, así que su CONFIGURACIÓN dice 8.000 y sus DATOS tienen padres de
        59.172. Comparar configuraciones habría dado luz verde."""
        gigante = "x" * (9000 * 4)
        v = se_puede_copiar(
            hash_origen=HASH,
            hash_destino=HASH,
            estrategia_destino="parent_child",
            techo_destino=8000,
            fragmentos=[_fragmento(), _fragmento(parent=gigante)],
        )
        assert not v.copiable
        assert "9000" in v.motivo
        assert "UPDATE" in v.motivo

    def test_should_refuse_when_the_source_has_no_chunks(self):
        v = se_puede_copiar(
            hash_origen=HASH,
            hash_destino=HASH,
            estrategia_destino="parent_child",
            techo_destino=8000,
            fragmentos=[],
        )
        assert not v.copiable


class TestElRemapeoAlcanzaLosTresIdentificadores:

    def test_should_remap_the_document_id_inside_chunk_metadata(self):
        """El tercero es el que se olvida, y el único que no da error al olvidarse: la
        agrupación por documento del retrieval usa el METADATO, no la columna."""
        destino_doc, destino_bot = uuid.uuid4(), uuid.uuid4()
        salida = remapea(_fragmento(), chatbot_id=destino_bot, document_id=destino_doc)

        assert salida["document_id"] == destino_doc
        assert salida["chatbot_id"] == destino_bot
        assert salida["chunk_metadata"]["document_id"] == str(destino_doc)

    def test_should_not_mutate_the_source_chunk(self):
        """Si el remapeo escribiera sobre el diccionario de origen, copiar a dos chatbots
        dejaría al segundo con los identificadores del primero."""
        original = _fragmento()
        metadato_antes = dict(original["chunk_metadata"])
        remapea(original, chatbot_id=uuid.uuid4(), document_id=uuid.uuid4())
        assert original["chunk_metadata"] == metadato_antes

    def test_should_keep_the_rest_of_the_metadata(self):
        salida = remapea(_fragmento(), chatbot_id=uuid.uuid4(), document_id=uuid.uuid4())
        assert salida["chunk_metadata"]["ancora"] == "art-4"

    def test_should_be_idempotent(self):
        """Remapear dos veces al mismo destino da lo mismo: la copia se puede relanzar sin
        dejar el corpus a medias ni duplicar identificadores."""
        doc, bot = uuid.uuid4(), uuid.uuid4()
        una = remapea(_fragmento(), chatbot_id=bot, document_id=doc)
        dos = remapea(una, chatbot_id=bot, document_id=doc)
        assert una == dos


class TestLaVerificacionDeCoherencia:

    def test_should_leave_zero_chunks_with_inconsistent_document_id(self):
        doc, bot = uuid.uuid4(), uuid.uuid4()
        copiados = [
            remapea(_fragmento(), chatbot_id=bot, document_id=doc) for _ in range(3)
        ]
        assert incoherentes(copiados) == []

    def test_should_catch_the_chunk_that_kept_the_old_metadata(self):
        doc, bot = uuid.uuid4(), uuid.uuid4()
        bueno = remapea(_fragmento(), chatbot_id=bot, document_id=doc)
        malo = {**bueno, "chunk_metadata": {**bueno["chunk_metadata"],
                                           "document_id": str(uuid.uuid4())}}
        assert incoherentes([bueno, malo]) == [malo]
