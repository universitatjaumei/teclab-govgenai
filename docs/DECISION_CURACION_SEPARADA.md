# Decisión: la curación del corpus es previa al asistente, no una función suya

**Fecha**: 2026-08-02
**Estado**: aceptada
**Origen**: experiencia real de la ingesta del corpus normativo de la UJI (`Descarregar_pdf/normativa_propia/`)
**Afecta a**: Bloque 9Q (ya cerrado), Bloque ING.0, Bloque SYNC, orden del roadmap de Fase 1

---

## La hipótesis que se cae

El diseño original asumía una **ingesta más o menos automatizada** de información pública: se
apunta el spider a un sitio web de la administración, el crawler descubre las páginas, el
sistema las ingiere y el chatbot responde sobre ellas. La calidad se resolvería después, con
detectores de incoherencias sobre el contenido ya ingerido.

Preparar el corpus normativo ha falsado esa hipótesis. Ese corpus es el **mejor caso posible**:
PDFs de normas publicadas, con un filtro de calidad previo de Secretaría General, un catálogo,
y numeración estable. Aun así, dejarlo en condiciones de ser ingerido ha exigido trabajo humano
sostenido y herramientas escritas a medida:

- derivar front-matter desde el catálogo (`genera_frontmatter.py`),
- decidir a mano qué versión es la consolidada y cuál está derogada, con un panel de revisión
  construido para eso (`build_dashboard_consolidacio.py` → `decisions_consolidacio.json`),
- parchear el generador de HTML para que emitiera `id` por artículo, sin lo cual no hay enlace
  profundo ni ancla estable,
- clasificar por ámbito y submaterias con un vocabulario que **todavía está pendiente de validar
  por Secretaría General**.

Nada de eso es ingesta. Es **curación**: decidir qué entra, en qué versión, con qué metadatos y
bajo qué taxonomía. Y es trabajo de criterio, no de proceso.

La conclusión operativa: si el mejor caso posible exige esto, un corpus de páginas web
rastreadas —sin control de calidad previo, sin versión canónica declarada, sin distinción entre
vigente y derogado— no es un corpus. Es materia prima.

---

## La decisión

**La curación es una actividad previa, humana y con producto propio. El asistente consume el
resultado; no lo produce.**

De ahí tres consecuencias:

1. **El crawler y el detector de incoherencias son herramientas de curación**, no de ingesta.
   Su función es ayudar a un humano a decidir qué merece entrar y a detectar qué está mal
   publicado. No alimentan el corpus por sí solos.

2. **La frontera entre las dos mitades es el contrato del corpus**, no una interfaz de código:
   `docs/CONTRATO_MD_CORPUS.md` (front-matter, manifiesto, anclas, vocabulario). El curador se
   obliga a emitir algo que lo cumpla; la plataforma se obliga a ingerir cualquier cosa que lo
   cumpla. Nada más cruza.

3. **No hay ingesta automática de web a corpus.** Que una página sea nueva o haya cambiado es
   una **señal para el curador**, nunca un disparador de ingesta.

---

## Lo que NO se decide aquí: separar en dos aplicaciones

Se consideró partir el sistema en dos productos independientes, con repositorio y despliegue
propios. **Se descarta**, por tres razones:

**El coste cae entero sobre lo compartido.** Habría que duplicar SSO SAML y PAT (bloque AUTH
completo), tenancy, `StorageService`, el pipeline de despliegue, CI y la generación Orval del
contrato. Y las piezas comunes son reales —Docling, el chunker, el servicio de embeddings, la
tabla de vocabulario, el propio contrato del corpus—, así que aparecería además un problema de
versionado de librería interna que hoy no existe.

**Rompería el único bucle que hace la curación sostenible.** Las preguntas que el asistente no
supo responder son la mejor fuente disponible de qué le falta al corpus. Eso ya está construido
(RAG.14) y ya está modelado: `HubContentFinding` admite **dos sujetos** y un `CHECK` que exige
exactamente uno —`site_id` para los hallazgos de auditoría de páginas, `chatbot_id` para los
huecos que nacen del uso—. Con dos aplicaciones separadas ese bucle cruza una frontera
organizativa y, en la práctica, deja de recorrerse. El corpus no se cura una vez: se cura
continuamente contra el uso real.

**El mecanismo para separar despliegues ya existe y es más barato.** `DEPLOY_MODE=cloud|edge|all`
ya clasifica routers y módulos. Si algún día la curación debe operarla otra unidad bajo
gobernanza distinta —Secretaría General sin acceso a las conversaciones, por ejemplo—, eso es un
perfil de despliegue más sobre el mismo codebase, no un fork.

**Lo que sí se decide**: la curación es un **producto distinto dentro del mismo codebase**.
Módulo propio, área propia en el frontend, nombre propio y navegación propia. Lo que se separa
es el oficio y la promesa, no el repositorio.

---

## Por qué importa la promesa, y no solo la arquitectura

Mientras el spider viva dentro de la interfaz de ingesta del chatbot, el producto sigue
afirmando implícitamente *«apunta al sitio web y el asistente aprende»*. Esa afirmación es la
que acaba de quedar desmentida, y es peligrosa porque no falla de forma visible: produce un
asistente que responde con seguridad apoyándose en una versión derogada de una norma. En un
asistente normativo eso es peor que un error, porque es indistinguible de un acierto.

Separar la curación es, sobre todo, dejar de hacer esa promesa.

---

## El detector de incoherencias tiene valor por sí solo

Auditar la coherencia de la información publicada en un sitio de administración pública es una
necesidad de transparencia y cumplimiento **independiente de que exista un chatbot**. Un informe
que dice «estas dos páginas afirman plazos distintos sobre el mismo trámite» le sirve al equipo
web aunque nadie despliegue un asistente.

Eso es un argumento para darle identidad de producto en vez de mantenerlo como una pestaña del
panel de ingesta: es lo que hace que la mitad de curación sea defendible por sí misma ante la
institución.

---

## Consecuencias concretas

### Sobre el Bloque 9Q (cerrado, no se reabre)

9Q construyó lo correcto y su código no cambia de comportamiento. Lo que cambia es **de qué es
parte**: deja de leerse como «calidad del contenido web ingerido, al servicio del RAG» y pasa a
leerse como **el motor de la herramienta de curación**. Su salida principal no es la higiene del
retriever sino el informe de auditoría; la higiene es el efecto secundario útil.

Esto ya estaba latente en el propio modelo de datos:

```python
class HubWebSite(HubOperationalBase):
    """Sitio web rastreado. Unidad de crawl + auditoría;
       propiedad de la organización, no del chatbot."""
```

`HubWebSite` cuelga de `organizacion_id` y **no tiene `chatbot_id`**. La entidad ya se diseñó
como propiedad de la organización, no del asistente.

### Sobre `CorpusSelectionService`

Es el punto exacto donde la materia prima se convierte en corpus, y cuando se escribió esto
estaba enterrado en `ingestion/quality/selection_service.py` como si fuera un detalle de la
ingesta. Hoy vive en `server/app/modules/curation/selection_service.py`. Es lo
contrario: es **el paso de publicación**, el momento en que un humano decide que una página
entra. Debe ser explícito y visible en la interfaz de curación.

### Sobre el orden del roadmap

El movimiento de código va **antes del Deploy**, no después. Los artefactos de despliegue
—imágenes, servicios de Cloud Run, CI— codifican la estructura de módulos y la clasificación de
routers; decidirla después de construir el pipeline obliga a rehacer parte de D.4 y D.5 y a
repetir la verificación contra producción. Un refactor pre-deploy solo arriesga en local, y lo
cubren los tests.

Orden resultante: **SYNC → SEC → CAL → CUR → Deploy**. CUR va detrás de CAL.1, que retira
NiceGUI y deja menos superficie que mover.

### Lo que NO cambia

- El comportamiento del crawler, los detectores y los informes. Es una reorganización, no una
  reescritura.
- El esquema de base de datos. `hub_web_sites`, `hub_crawled_pages`, `hub_corpus_selections` y
  `hub_content_findings` se quedan como están: ya están bien modeladas.
- El bucle de RAG.14. Se conserva y se refuerza: es la conexión legítima entre las dos mitades.

---

## Cómo se sabrá si la decisión fue buena

- Que cargar un corpus nuevo no exija tocar código de la plataforma, solo cumplir el contrato.
- Que el informe de auditoría se entregue a un equipo web que no tiene chatbot, y le sirva.
- Que nadie vuelva a preguntar si el asistente «se actualiza solo» al cambiar el sitio web.
