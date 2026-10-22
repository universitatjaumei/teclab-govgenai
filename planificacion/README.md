# `planificacion/` — el plan de la Fase 1, su cursor y el historial

Estos documentos no describen el producto: **lo dirigieron**. **El estado del desarrollo ya no está
aquí**: está en las *issues* y los hitos de GitHub, ordenados por temas en
[`../ROADMAP.md`](../ROADMAP.md). Esta carpeta guarda el plan de la Fase 1, escrito como prompts, y
el historial, que sigue creciendo. La documentación estable —arquitectura, decisiones,
manuales— vive en `docs/`.

> **Si lo que buscas es qué garantiza el sistema, esto no es.** Un plan dice «haz X»; lo que
> puedes dar por cierto al construir encima está en
> [`../docs/ESPECIFICACIONES.md`](../docs/ESPECIFICACIONES.md), organizado por capacidad y no por
> orden de ejecución. Aquí está **qué falta y en qué orden**; allí, **qué se puede romper**.

| Fichero | Para qué |
|---|---|
| `PROJECT_STATE.md` | **El cursor de la Fase 1**, con sus bloques y el modelo sugerido de cada prompt. Fue la fuente de verdad del progreso mientras el desarrollo tuvo un solo escritor; dejó de actualizarse el 2026-09-26 y se conserva como registro. Lo que quede pendiente en él se abre como *issue* cuando se retoma. |
| `HISTORIAL.md` | El archivo: una fila por paso cerrado —prompt o *issue*—, con qué se desvió del plan y qué defecto apareció al verificar. Se consulta para saber **por qué** algo se hizo así. |
| `PLAN_DESARROLLO.md` | El plan a alto nivel: fases, subfases y qué entrega cada una. |
| `PLAN_TDD_DETALLADO.md` | Prompts detallados de las fases iniciales. |
| `Plan_TDD_Fase1.md` | **El índice** de la Fase 1 — hub informativo, personalización y redacción. Eran 27.449 líneas en un fichero; ahora cada bloque y cada fase viven en `fase1/`, con su número de orden delante. Fue el último plan escrito como prompts. |
| `fase1/` | Un fichero por bloque o fase: los prompts, sus tests mínimos y su verificación. Es lo que se lee para implementar, y lo que se puede revisar en un *pull request*. |
| `Plan_TDD_Fase2.md`, `Plan_TDD_Fase3.md` | **Cerrados el 2026-09-23 y no se van a ejecutar.** Los sustituyen los temas 4 («automatización gobernada») y 8 («trámites asistidos con IA») de [`../ROADMAP.md`](../ROADMAP.md), cada uno con cuatro hitos en GitHub. Se conservan como historia: la cabecera de cada uno dice qué cayó, qué se hizo bajo otro nombre y qué sobrevive. |

## Si llegas de fuera: esto es un registro, no una descripción

**La hoja de ruta pública es [`../ROADMAP.md`](../ROADMAP.md)**, por temas y con estado, enlazada a
las *issues* y a los hitos de GitHub. Esta carpeta dirige el desarrollo; el roadmap lo cuenta hacia
fuera. Si lo que buscas es qué está previsto construir, empieza por ahí.

Los documentos de plan están escritos **en futuro**, y algunos describen caminos que se
recorrieron a medias o no se recorrieron. Los dos mayores:

- **El cliente NiceGUI**, que se retiró entero el 2026-09-04 junto con 574 ficheros. `Plan_TDD_Fase2.md`
  se titula «Automatización, Thin Client y Migración NiceGUI» y no queda nada de eso en el árbol.
- **Docling**, retirado en el bloque EXT.3. Al corpus sólo entra `.md` conforme a
  [`../docs/CONTRATO_MD_CORPUS.md`](../docs/CONTRATO_MD_CORPUS.md), y el contexto se extrae con
  pdfplumber.

Son **473 menciones repartidas en 27 ficheros**, y no se han corregido a propósito. Un plan
enmendado a posteriori para que parezca acertado deja de servir para lo único que sirve un plan
viejo: entender por qué se decidió lo que se decidió, y qué costó averiguar que estaba mal. Que
`HISTORIAL.md` hable de NiceGUI es correcto, porque pasó.

**Lo que NO debes hacer es leer un plan como si describiera el sistema de hoy.** Para eso están
[`../docs/ESPECIFICACIONES.md`](../docs/ESPECIFICACIONES.md) (qué garantiza), `../AGENTS.md` (dónde
vive cada cosa) y el código.

## Cómo se usan

La metodología está en `CLAUDE.md` y en `docs/METODOLOGIA_AGENTICA.md`. En resumen: el desarrollo
avanza por **bloques** de prompts; cada prompt sigue RED → GREEN → REFACTOR, cierra con un commit
propio, y al cerrarlo se mueve el cursor en `PROJECT_STATE.md` y se añade una fila **arriba** de la
tabla de `HISTORIAL.md`.

Los prompts se leen **verbatim** del plan: están redactados para ejecutarse tal cual, con su
etiqueta de modelo sugerido. Si el plan y el código real no coinciden, se aplica la interpretación
más fiel al prompt y se registra como «desviación documentada» en el historial.

## Por qué están en el repositorio y no sólo en local

Porque sin ellos un clon nuevo no puede continuar el trabajo: se pierde el cursor y se pierden los
prompts. Y porque el historial explica decisiones que el código no explica por sí solo — por qué se
descartó una opción, qué se rompió al intentarlo de la otra manera.
