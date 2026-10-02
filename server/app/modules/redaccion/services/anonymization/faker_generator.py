"""FakerGenerator — generación contextual de valores sintéticos con cache.

Extraído del legacy AnonymizationContext._generate_fake() para permitir
reutilización sin necesidad de invocar todo el motor de anonimización.

Garantías:
- Determinismo por valor original (mismo input → mismo fake, dentro de la misma
  instancia).
- Cache bidireccional (real↔fake) para soportar deanonimización.
- Resolución de colisiones por reintento (hasta 10) y sufijo numérico.
- Contexto por campo (firstname/lastname/fullname) para generar nombres
  coherentes en formularios estructurados.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from faker import Faker


class FakerGenerator:
    """Genera valores sintéticos consistentes y deterministas por entidad.

    `fake_to_real` y `real_to_fake` se mantienen sincronizados; al detectar
    una colisión se reintenta hasta 10 veces y, si persiste, se añade un
    sufijo numérico para garantizar unicidad.
    """

    def __init__(self, locale: str = "es_ES", seed: int | None = None) -> None:
        self.faker = Faker(locale)
        if seed is not None:
            Faker.seed(seed)
            self.faker.seed_instance(seed)
        self.fake_to_real: dict[str, str] = {}
        self.real_to_fake: dict[str, str] = {}
        self.stats: dict[str, int] = {}

    def generate(self, entity_type: str, original: Any, context: str = "") -> str:
        """Devuelve un valor falso determinista por (entity_type, original)."""
        if original is None or (isinstance(original, float) and pd.isna(original)):
            return original  # type: ignore[return-value]

        original_str = str(original)
        if original_str in self.real_to_fake:
            return self.real_to_fake[original_str]

        fake = ""
        for _ in range(10):
            fake = self._sample(entity_type, original_str, context)
            if fake not in self.fake_to_real:
                self._register(entity_type, original_str, fake)
                return fake

        fake_with_suffix = f"{fake}_{len(self.fake_to_real)}"
        self._register(entity_type, original_str, fake_with_suffix)
        return fake_with_suffix

    def _register(self, entity_type: str, original: str, fake: str) -> None:
        self.fake_to_real[fake] = original
        self.real_to_fake[original] = fake
        self.stats[entity_type] = self.stats.get(entity_type, 0) + 1

    def _sample(self, entity_type: str, original: str, context: str) -> str:
        ctx_lower = context.lower()

        if entity_type == "EMAIL":
            return self.faker.email()
        if entity_type == "PHONE":
            return f"+34 {self.faker.phone_number()}"
        if entity_type in ("DNI", "ID"):
            return self.faker.bothify(text="########?")
        if entity_type == "NIE":
            return self.faker.bothify(text="?#######?")
        if entity_type == "PASSPORT":
            return self.faker.bothify(text="???######")
        if entity_type == "IBAN":
            return f"ES{self.faker.random_number(digits=22, fix_len=True)}"
        if entity_type in ("PERSON_NAME", "PERSON"):
            # **El falso tiene la forma del verdadero** (UTL.2, issue #191): tantas palabras como
            # el original. Antes decidía sólo por la cabecera, y «Nombre completo» contiene «nom»,
            # así que «Ana García López» salía como un nombre de pila suelto: anonimizado, pero no
            # verosímil, y la columna perdía su forma.
            palabras = max(len(original.split()), 1)
            if any(x in ctx_lower for x in ("apellido", "surname", "cognom")):
                return " ".join(self._una_palabra(self.faker.last_name) for _ in range(palabras))
            if palabras == 1:
                return self._una_palabra(self.faker.first_name)
            return " ".join(
                [self._una_palabra(self.faker.first_name)]
                + [self._una_palabra(self.faker.last_name) for _ in range(palabras - 1)]
            )
        if entity_type == "CREDIT_CARD":
            return self.faker.credit_card_number(card_type=None)
        if entity_type == "NSS":
            return self.faker.numerify("##/########/##")
        if entity_type == "DATE":
            return self.faker.date_between(
                start_date="-80y", end_date="today"
            ).strftime("%d/%m/%Y")
        if entity_type == "ADDRESS":
            return self.faker.address().replace("\n", ", ")
        if entity_type == "POSTAL_CODE":
            return self.faker.postcode()
        if entity_type in ("ORG", "ORGANIZATION", "COMPANY"):
            return self.faker.company()
        if entity_type == "CITY":
            return self.faker.city()
        return (
            self.faker.word() if not original[0].isdigit() else self.faker.numerify("####")
        )

    def _una_palabra(self, generar) -> str:
        """Un valor de una sola palabra: Faker da a veces compuestos («del Río», «María José»)."""
        valor = generar()
        for _ in range(10):
            if " " not in valor:
                return valor
            valor = generar()
        return valor.replace(" ", "")

    def get_stats(self) -> dict[str, int]:
        return dict(self.stats)

    def reset(self) -> None:
        self.fake_to_real.clear()
        self.real_to_fake.clear()
        self.stats.clear()
