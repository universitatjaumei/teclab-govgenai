"""Tests del motor de anonimización migrado en 9R.5.5.

Migrados y adaptados desde client_app/tests/test_ner_anonymizer.py,
test_anonymizer_patterns.py, test_anonymizer.py, test_anonymizer_extended.py.

11 tests cubren: NER persons, regex DNI/IBAN, anclajes, fallback sin spaCy,
faker determinista, contexto de apellidos, AEPD disposición 7ª, dataframe
con row count preservado, PDF→markdown sintético.
"""
from __future__ import annotations

import pandas as pd
import pytest

from server.app.modules.redaccion.services.anonymization.anonymizer import (
    AnonymizationContext,
)
from server.app.modules.redaccion.services.anonymization.faker_generator import (
    FakerGenerator,
)


@pytest.fixture
def ctx() -> AnonymizationContext:
    """El contexto de los tests, **con semilla**.

    Sin ella, lo que Faker escupe depende de lo que haya corrido antes en el proceso:
    `FakerGenerator.__init__` llama a `Faker.seed()`, que es un **método de clase** y siembra el
    generador compartido. Cualquier test de cualquier carpeta que construya un generador
    sembrado deja fijada la secuencia para todo lo que venga después.

    Eso tumbó CI el 2026-09-15 y **volvió a tumbarlo el 2026-09-30**, esta vez sin que nadie
    tocara la anonimización: un bloque nuevo añadió ficheros de test, cambió el orden de
    recolección, y la secuencia global cayó en un nombre falso que contenía el real. El test de
    más abajo ya se había arreglado así; éste se quedó sin arreglar porque entonces no falló.
    """
    return AnonymizationContext(faker_seed=42)


# ---------------------------------------------------------------------------
# 1. NER detecta personas (sin assert duro si spaCy no está)
# ---------------------------------------------------------------------------

def test_pii_detector_identifies_persons_with_ner(ctx: AnonymizationContext) -> None:
    """Si spaCy está disponible, debe detectar nombres propios via NER."""
    text = "El estudiante Juan Pérez aprobó la asignatura."
    anonymized = ctx.anonymize(text, allowed_types=["PERSON_NAME"])
    if ctx.spacy_available:
        assert "Juan Pérez" not in anonymized
    else:
        # Sin spaCy degrada, no rompe el flujo
        assert isinstance(anonymized, str)


# ---------------------------------------------------------------------------
# 2. DNI/NIF por regex
# ---------------------------------------------------------------------------

def test_pii_detector_identifies_dni_nif_with_regex(ctx: AnonymizationContext) -> None:
    text = "DNI del solicitante: 12345678Z"
    anonymized = ctx.anonymize(text, allowed_types=["DNI"])
    assert "12345678Z" not in anonymized
    # debe haber introducido un fake del DNI
    assert ctx.real_to_fake.get("12345678Z") is not None


# ---------------------------------------------------------------------------
# 3. IBAN por regex
# ---------------------------------------------------------------------------

def test_pii_detector_identifies_iban_with_regex(ctx: AnonymizationContext) -> None:
    iban = "ES7621000418401234567891"
    anonymized = ctx.anonymize(f"Cuenta: {iban}", allowed_types=["IBAN"])
    assert iban not in anonymized
    assert ctx.real_to_fake.get(iban) is not None


# ---------------------------------------------------------------------------
# 4. Anclajes de formulario
# ---------------------------------------------------------------------------

def test_pii_detector_uses_form_anchors_for_field_context(
    ctx: AnonymizationContext,
) -> None:
    """Los anclajes de formulario señalan el nombre y los apellidos, y se sustituyen.

    **Se afirma sobre la detección y sobre el cambio, no sobre la ausencia del literal.** Es la
    misma corrección que el test de más abajo ya lleva, y aquí llegó tarde: el 2026-09-30 esto
    tumbó CI porque Faker devolvió «Luis Manuel» como nombre falso, que contiene el real.

    Que el sustituto coincida con el original **no es un fallo del anonimizador**: detectó el
    ancla, cogió los offsets buenos y sustituyó. Afirmar `"Luis" not in anonymized` convertía
    una coincidencia de Faker en un rojo, y —peor— dejaba pasar el caso de verdad grave, porque
    un anonimizador que no tocara nada también podría dar un texto sin la palabra si el azar
    ayudaba. Lo que se comprueba ahora es lo que se quiere garantizar.

    **Y al escribirlo apareció un defecto de verdad**, que quedó anotado aquí unas horas: el
    ancla de nombre abarcaba `«Luis Apellidos»` —se comía la etiqueta del campo siguiente— y la
    salida de este mismo caso era `«Nombre: Manuela: Cantón»`, sin el rótulo «Apellidos».
    Arreglado en la issue #193, con su propio fichero de tests; **por eso la igualdad de abajo
    vuelve a ser una igualdad**. Mientras el defecto estuvo vivo fue un `startswith`, para
    afirmar lo que pasaba sin fingir que pasaba lo correcto.
    """
    text = "Nombre: Luis Apellidos: Pérez Martínez"
    anonymized = ctx.anonymize(text)

    anchors = ctx.get_detected_anchors()
    assert any(a["field_type"] == "firstname" for a in anchors)
    assert any(a["field_type"] == "lastname" for a in anchors)

    # Los offsets señalan el valor y no la etiqueta: si se desplazaran, la sustitución tocaría
    # el trozo equivocado y ningún assert sobre el texto de salida lo vería.
    nombre = next(a for a in anchors if a["field_type"] == "firstname")
    apellidos = next(a for a in anchors if a["field_type"] == "lastname")
    assert text[nombre["value_start"] : nombre["value_end"]] == "Luis"
    assert text[apellidos["value_start"] : apellidos["value_end"]] == "Pérez Martínez"

    # Y algo se sustituyó de verdad: sin esto, un anonimizador que no tocara nada pasaría.
    assert anonymized != text

    hint = ctx.get_form_structure_hint()
    assert hint is not None
    assert "NOMBRE DE PILA" in hint
    assert "APELLIDOS" in hint


# ---------------------------------------------------------------------------
# 5. Fallback sin spaCy → regex+anclajes siguen funcionando
# ---------------------------------------------------------------------------

def test_pii_detector_degrades_to_regex_only_without_spacy(monkeypatch) -> None:
    """Forzamos _nlp=None y verificamos que regex + anclajes siguen funcionando.

    El ancla se comprueba por la DETECCIÓN, no por el texto de salida, y eso arregla un rojo que
    tumbó CI el 2026-09-15 (run 34974628381). La versión anterior afirmaba
    `assert "Marta" not in anonymized`, o sea que el nombre falso nunca coincidiera con el real.

    **Y no era aleatoriedad, era estado filtrado entre tests**, que es lo que `-n0` en CI existe
    para cazar. `FakerGenerator.__init__` llama a `Faker.seed(seed)`, que es un **método de
    clase**: siembra el generador compartido de todo el proceso. Dos tests más abajo en este
    mismo fichero construyen `FakerGenerator(seed=42)`, así que en una ejecución **en serie** la
    secuencia global queda fijada y este test —que creaba el contexto **sin semilla**— dejaba de
    ser aleatorio y caía siempre en «Marta». Con `-n auto` no salía porque el reparto entre
    procesos cambia quién sembró antes; en serie es determinista. (Sin ese estado previo el
    choque existe igual, pero es raro: medido sobre 3.000 contextos frescos, 3 devuelven
    «Marta», un 0,1 %.)

    El rojo escondía además un error de fondo: que el nombre falso coincida con el real **no es
    un fallo del anonimizador**, que hizo su trabajo —detectar el ancla y sustituir—. La garantía
    es que `ANCHOR_FIRSTNAME` dispara sin spaCy; el valor concreto que escupe Faker es asunto de
    Faker. El DNI y el correo sí se comprueban por el texto, porque ahí el sustituto tiene otra
    forma y no puede coincidir por azar.

    La semilla explícita hace el test independiente de lo que corriera antes, que es la mitad del
    arreglo; la otra mitad es afirmar sobre la detección.
    """
    ctx = AnonymizationContext(faker_seed=42)
    ctx._nlp = None  # type: ignore[attr-defined]
    assert not ctx.spacy_available

    text = "DNI: 12345678Z y email a juan@example.com. Nombre: Marta"
    anonymized = ctx.anonymize(text)
    assert "12345678Z" not in anonymized
    assert "juan@example.com" not in anonymized

    anclas = ctx.get_detected_anchors()
    assert any(a.get("field_type") == "firstname" for a in anclas), (
        f"Sin spaCy, «Nombre: Marta» lo tiene que cazar ANCHOR_FIRSTNAME. Anclas detectadas: "
        f"{anclas}"
    )
    # Y el valor que el ancla señala es el nombre, no la etiqueta: si los offsets se
    # desplazaran, la sustitución tocaría el trozo equivocado y el test anterior no lo veía.
    ancla = next(a for a in anclas if a.get("field_type") == "firstname")
    assert text[ancla["value_start"] : ancla["value_end"]] == "Marta"


# ---------------------------------------------------------------------------
# 6. Faker determinista por valor original (dentro de la instancia)
# ---------------------------------------------------------------------------

def test_faker_generator_is_deterministic_per_value() -> None:
    fakes = FakerGenerator(seed=42)
    first = fakes.generate("EMAIL", "alice@example.com")
    second = fakes.generate("EMAIL", "alice@example.com")
    assert first == second
    assert first != "alice@example.com"


# ---------------------------------------------------------------------------
# 7. Contexto lastname → faker.last_name()
# ---------------------------------------------------------------------------

def test_faker_generator_uses_lastname_after_firstname_anchor() -> None:
    fakes = FakerGenerator(seed=42)
    # Pedimos un fake con contexto "apellido" → debe ser un apellido,
    # NO usar first_name() (heurística del legacy).
    fake_lastname = fakes.generate("PERSON_NAME", "Pérez Martínez", context="apellido")
    fake_firstname = fakes.generate("PERSON_NAME", "Luis", context="nombre")
    assert fake_lastname != "Pérez Martínez"
    assert fake_firstname != "Luis"
    # Garantizamos que ambos son strings distintos no vacíos
    assert isinstance(fake_lastname, str)
    assert isinstance(fake_firstname, str)
    assert fake_lastname != fake_firstname


# ---------------------------------------------------------------------------
# 8. Disposición 7ª LOPDGDD (AEPD) sobre DNI
# ---------------------------------------------------------------------------

def test_anonymizer_handles_aepd_disposicion_septima_for_dni(
    ctx: AnonymizationContext,
) -> None:
    """DNI 12345678Z → ***4567** (muestra dígitos 4-7)."""
    result = ctx.anonymize_document_id("12345678Z", mode="AEPD")
    assert result == "***4567**"


# ---------------------------------------------------------------------------
# 9. Anonimizar DataFrame preserva número de filas
# ---------------------------------------------------------------------------

def test_anonymize_tabular_preserves_row_count(ctx: AnonymizationContext) -> None:
    df = pd.DataFrame(
        {
            "Nombre": ["Juan Pérez", "María García", "Carlos Ruiz"],
            "Email": ["juan@x.com", "maria@y.com", "carlos@z.com"],
        }
    )
    result = ctx.anonymize_dataframe(
        df,
        {
            "Nombre": {"type": "PERSON_NAME", "mode": "FAKER"},
            "Email": {"type": "EMAIL", "mode": "FAKER"},
        },
    )
    assert len(result) == 3
    assert set(result["Nombre"]).isdisjoint({"Juan Pérez", "María García", "Carlos Ruiz"})
    assert set(result["Email"]).isdisjoint({"juan@x.com", "maria@y.com", "carlos@z.com"})


# ---------------------------------------------------------------------------
# 10 + 11. PDF→markdown sintético: spans sustituidos, resto verbatim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anonymize_pdf_to_text_returns_markdown_with_substituted_spans(
    tmp_path,
) -> None:
    """Verifica que el flujo PDF→markdown→anonimización produce un .md
    sin PII detectada y con el resto del texto preservado.

    Usamos un PDF generado con reportlab que incluye DNI + email + nombre.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    from server.app.core.storage import FsspecStorageService
    from server.app.modules.redaccion.pipelines.contracts import StorageRef
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        TestDataAnonymizerService,
    )

    pdf_path = tmp_path / "pii.pdf"
    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawString(100, 750, "Informe de gestion 2026")
    c.drawString(100, 720, "DNI: 12345678Z")
    c.drawString(100, 690, "Email: juan@example.com")
    c.drawString(100, 660, "Total ejecutado: 100.000 EUR")
    c.save()

    bucket_root = tmp_path / "bucket"
    bucket_root.mkdir()
    storage = FsspecStorageService(backend="file", bucket=str(bucket_root))
    await storage.put("pii.pdf", pdf_path.read_bytes())

    service = TestDataAnonymizerService(storage=storage)
    result = await service.anonymize_pdf_to_text(StorageRef(bucket="bucket", key="pii.pdf"))

    md_bytes = await storage.get(result.synthetic_ref.key)
    md = md_bytes.decode("utf-8")

    # PII desaparecida
    assert "12345678Z" not in md
    assert "juan@example.com" not in md

    # Texto no-PII preservado
    assert "Informe de gestion 2026" in md
    assert "Total ejecutado" in md
    assert result.spans_applied >= 2


@pytest.mark.asyncio
async def test_anonymize_pdf_to_text_preserves_non_pii_content_verbatim(
    tmp_path,
) -> None:
    """Refuerza: tokens no-PII (números, palabras comunes) quedan intactos."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    from server.app.core.storage import FsspecStorageService
    from server.app.modules.redaccion.pipelines.contracts import StorageRef
    from server.app.modules.redaccion.services.test_data_anonymizer import (
        TestDataAnonymizerService,
    )

    pdf_path = tmp_path / "neutral.pdf"
    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawString(100, 750, "Resumen de actividades del trimestre")
    c.drawString(100, 720, "Total beneficiarios: 245")
    c.drawString(100, 690, "Importe total ejecutado: 100000 EUR")
    c.save()

    bucket_root = tmp_path / "bucket"
    bucket_root.mkdir()
    storage = FsspecStorageService(backend="file", bucket=str(bucket_root))
    await storage.put("neutral.pdf", pdf_path.read_bytes())

    service = TestDataAnonymizerService(storage=storage)
    result = await service.anonymize_pdf_to_text(StorageRef(bucket="bucket", key="neutral.pdf"))

    md = (await storage.get(result.synthetic_ref.key)).decode("utf-8")
    assert "Resumen de actividades del trimestre" in md
    assert "245" in md
    assert "100000" in md
