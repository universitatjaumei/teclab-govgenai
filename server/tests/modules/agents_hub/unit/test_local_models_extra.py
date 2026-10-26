"""Tests D.4.0 — los modelos locales son un extra de instalación, no una dependencia base.

`torch`, `transformers` y `sentence-transformers` están en el proyecto por
`LocalEmbeddingService` (BGE-M3) y `LocalReranker`. Con embeddings de Vertex y el reranker
apagado —el plan de despliegue— **no se usan en ejecución, pero se pagan enteros**: medido en
EXT.3, `sentence-transformers` son 216 MB, `torch` 172 MB, y entre los tres se llevan
prácticamente todo el tiempo de arranque. `pdfplumber`, que sí se usa, cuesta 5 MB.

**Esto no retira una capacidad, la hace opcional.** El modo edge sigue pudiendo usar modelos
locales: instala el extra y funciona igual. Lo que cambia es que un despliegue que no los use
deje de cargarlos.

El fallo tiene que **explicarse**: un `ModuleNotFoundError: torch` en mitad de una ingesta no
le dice a nadie qué instalar.
"""
from __future__ import annotations

import builtins
import sys

import pytest


def _sin_pila_de_modelos(monkeypatch):
    """Simula que el extra NO está instalado.

    Se simula en vez de desinstalarlo porque la suite corre CON el extra —es como corre CI—,
    y aun así el camino del error tiene que estar probado: es el que verá quien despliegue
    sin él.
    """
    prohibidos = {"sentence_transformers", "torch", "transformers"}
    import_real = builtins.__import__

    def _import(nombre, *args, **kwargs):
        if nombre.split(".")[0] in prohibidos:
            raise ImportError(f"No module named '{nombre}'")
        return import_real(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    for modulo in list(sys.modules):
        if modulo.split(".")[0] in prohibidos:
            monkeypatch.delitem(sys.modules, modulo, raising=False)


class TestElEmpaquetado:

    def test_should_declare_local_models_as_an_optional_extra(self):
        from pathlib import Path

        import tomllib

        datos = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        base = " ".join(datos["project"]["dependencies"])
        extras = datos["project"].get("optional-dependencies", {})

        assert "local-models" in extras, (
            "no existe el extra `local-models`; sin él no hay forma de instalar la "
            "aplicación sin la pila de modelos"
        )
        def _nombres(especificaciones: list[str]) -> set[str]:
            """Nombre de paquete sin la restricción de versión.

            Se compara por nombre exacto y no con `in`: `"transformers" in
            "sentence-transformers"` es cierto, y con esa comprobación el test pasaría
            aunque el paquete no estuviera declarado en ningún sitio.
            """
            import re

            return {re.split(r"[<>=!\[ ]", e.strip())[0] for e in especificaciones}

        nombres_extra = _nombres(extras["local-models"])
        nombres_base = _nombres(datos["project"]["dependencies"])

        for paquete in ("torch", "torchvision", "sentence-transformers"):
            assert paquete in nombres_extra, f"{paquete} debería estar en el extra"
            assert paquete not in nombres_base, (
                f"{paquete} sigue siendo dependencia base: se instalaría siempre"
            )

        # `transformers` no se declara en ningún sitio: llega como transitiva de
        # `sentence-transformers`. Sin el extra, no se instala.
        assert "transformers" not in nombres_base
        assert base is not None  # el nombre se conserva por legibilidad del fallo


class TestNadieCargaLaPilaSinQuererlo:

    def test_should_not_import_sentence_transformers_when_importing_the_app(self):
        """`sentence_transformers` es el que este proyecto sí controla, y el más caro (216 MB).

        Lo arrastraba `langchain_text_splitters`: su `__init__.py` importa de forma ansiosa
        el submódulo `sentence_transformers`, y no hay manera de cargar un submódulo sin
        ejecutar el `__init__` del paquete. Por eso el chunker lo importa dentro del
        constructor: el proceso que solo atiende chat nunca lo paga.

        **Por qué este test NO comprueba también `torch` y `transformers`**: con el extra
        instalado —como corre CI y como corre esta suite— los carga `langchain_core`, que
        hace `try: from transformers import GPT2TokenizerFast / except ImportError` para
        decidir si sabe contar tokens. Eso no está en nuestra mano, y **no importa**: sin el
        extra esos paquetes no están instalados, el `except` salta y no se carga nada. Que
        aquí aparezcan es consecuencia de tenerlos, no de necesitarlos.
        """
        import subprocess

        codigo = (
            "import server.app.main, sys; "
            "print('sentence_transformers' in sys.modules)"
        )
        resultado = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True,
            text=True,
            cwd="..",
            timeout=600,
            check=False,
        )
        assert resultado.returncode == 0, resultado.stderr[-800:]
        assert resultado.stdout.strip().endswith("False"), (
            "importar la app carga sentence_transformers: "
            f"{resultado.stdout.strip()}"
        )

    def test_langchain_core_should_probe_transformers_not_require_it(self):
        """La afirmación en la que se apoya el test de arriba, comprobada en vez de supuesta:
        si `langchain_core` exigiera `transformers`, quitarlo del manifiesto rompería la
        aplicación entera en vez de ahorrar memoria.

        **Se comprueba la PROPIEDAD, no el nombre de una variable privada.** Hasta DEP.1 esto
        buscaba el literal `_HAS_TRANSFORMERS = False` en el fuente de `langchain_core`, y al
        subir de 1.5.5 a 1.6.2 se puso rojo sin que nada estuviera mal: la librería había
        cambiado a un import perezoso dentro de la función, con caché y un mensaje que dice qué
        instalar — o sea, mejor que antes. Un test clavado a la implementación de un tercero se
        rompe cuando el tercero mejora, y eso enseña a ignorarlo.
        """
        import re
        from pathlib import Path

        import langchain_core.language_models.base as base

        # NO se comprueba que `transformers` falte. Sería una premisa que sólo se cumple en el
        # entorno base: CI sincroniza con `uv sync --locked --all-extras` y allí está instalado,
        # así que la afirmación pondría el job en rojo sin que nada estuviera mal. Es el mismo
        # error que se cometió en el guardarraíl de DEP.1 y se corrigió igual: **lo que se fija
        # se lee del fuente, no del entorno**, y así vale en las dos máquinas.
        fuente = Path(base.__file__).read_text(encoding="utf-8")
        importa_transformers = [
            linea
            for linea in fuente.splitlines()
            if re.match(r"\s*(from transformers import|import transformers)", linea)
        ]
        assert importa_transformers, (
            "Ya no se importa `transformers` en este módulo. Si la dependencia ha desaparecido "
            "del todo, este test sobra; compruébalo y quítalo en vez de dejarlo pasando en "
            "verde sobre algo que ya no existe."
        )
        assert all(linea.startswith((" ", "\t")) for linea in importa_transformers), (
            "`transformers` se importa en el NIVEL SUPERIOR del módulo. Da igual que esté "
            "dentro de un `try`: lo que importa es que no se pague al importar. Tiene que ir "
            "dentro de la función que lo usa.\n"
            f"Líneas: {importa_transformers}"
        )


class TestElErrorExplicaQueInstalar:

    async def test_should_explain_how_to_install_when_local_embedding_is_used(
        self, monkeypatch
    ):
        from server.app.modules.agents_hub.services.embedding_service import (
            LocalEmbeddingService,
        )

        _sin_pila_de_modelos(monkeypatch)

        with pytest.raises(RuntimeError) as exc:
            await LocalEmbeddingService().embed("hola")

        mensaje = str(exc.value)
        assert "local-models" in mensaje, mensaje
        assert "uv sync" in mensaje, mensaje

    async def test_should_explain_how_to_install_when_local_reranker_is_used(
        self, monkeypatch
    ):
        from server.app.modules.agents_hub.services.reranker import LocalReranker

        _sin_pila_de_modelos(monkeypatch)

        with pytest.raises(RuntimeError) as exc:
            await LocalReranker().rerank("consulta", ["a", "b"], top_k=1)

        mensaje = str(exc.value)
        assert "local-models" in mensaje, mensaje
        assert "uv sync" in mensaje, mensaje

    def test_should_not_break_the_google_service_without_the_extra(self, monkeypatch):
        """El camino que sí se usa en el despliegue no puede depender del extra."""
        _sin_pila_de_modelos(monkeypatch)

        from server.app.modules.agents_hub.services.embedding_service import (
            GoogleEmbeddingService,
        )

        servicio = GoogleEmbeddingService(model_name="text-embedding-004", client=object())
        assert servicio.dimensions == 1024


class TestLaCapacidadNoSeRetira:
    """El modo edge sigue funcionando: con el extra instalado, nada cambia."""

    def test_local_embedding_should_still_declare_its_provenance(self):
        from server.app.modules.agents_hub.services.embedding_service import (
            LocalEmbeddingService,
        )

        servicio = LocalEmbeddingService()
        assert servicio.model_name == "BAAI/bge-m3"
        assert servicio.dimensions == 1024

    def test_local_reranker_should_still_be_constructible(self):
        from server.app.modules.agents_hub.services.reranker import LocalReranker

        assert LocalReranker().model_name == "BAAI/bge-reranker-v2-m3"
