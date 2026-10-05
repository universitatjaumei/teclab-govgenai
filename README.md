# Gov Gen AI Platform

Plataforma de IA generativa para administración pública. Nace de la actividad investigadora del
grupo **INNOVAP** (Derecho Público e Innovación) de la Universitat Jaume I, y su finalidad es ofrecer una solución de **software libre multiorganización**, utilizable por otras administraciones públicas y en particular por **entidades locales**, que rara vez tienen capacidad para construir algo así por su cuenta.

Ese propósito no es una declaración de intenciones del README: es lo que explica media
arquitectura. La jerarquía Plataforma → Organización → Chatbot, la separación entre configuración y
dato operacional, y la frontera edge/cloud existen porque el sistema tiene que servir a
instituciones distintas sin que ninguna vea los datos de otra. Un sistema hecho para una sola
institución no necesitaría nada de eso.

El principio que guía el desarrollo, en términos académicos, es el de **conformidad por diseño**
(*compliance by design*): las obligaciones jurídicas no se documentan aparte del sistema, se
incorporan a su construcción. Cada actuación asistida por IA deja evidencia de supervisión humana,
de procedencia de la información y del tratamiento de datos personales aplicado, y esas garantías
se traducen en comprobaciones ejecutables y pruebas automáticas —*compliance as code*— en lugar de
descansar en la buena fe o en auditorías puntuales.

De ahí salen decisiones que de otro modo parecerían caprichos técnicos: que el determinismo se
prefiera al modelo generativo siempre que alcance, que ninguna afirmación se emita sin cita a su
fuente, que la respuesta de indisponibilidad sea una función del sistema y no un fallo, y que la
frontera edge/cloud esté implementada en el código y vigilada por tests en vez de prometida en un
contrato. El desarrollo del principio y su encaje normativo —Reglamento (UE) 2024/1689, RGPD, Leyes
39/2015 y 40/2015, Esquema Nacional de Seguridad— está en `docs/PRESENTACION_PROYECTO.md` y
`docs/MARCO_GOBERNANZA_IA.md`.

Lo que hace, sobre una misma base:

| Área | Qué hace |
|---|---|
| **Chatbots** | Asistentes con recuperación sobre corpus normativo propio (RAG en tres niveles), publicables como widget embebible o como agente identificado. |
| **Informes** | Redacción asistida de informes: extracción determinista de PDF y hojas de cálculo, transformación declarativa de los datos, gráficos, y valoración escrita por el modelo y **aprobada o editada por una persona** antes de exportar. Cuando un documento es tan irregular que hay que programar su lectura, el código se audita y se ejecuta en un sandbox sin red. |
| **Automatización** | El catálogo de funciones: código determinista con contrato declarado, versionado e inmutable, que se registra sin aprobación previa y se revisa después. También **registra lo que corre fuera** —un cuaderno se da de alta por su hash, sin ejecutarlo— para que la institución sepa qué automatizaciones circulan. |
| **Agentes de unidad** | Una unidad publica un agente —un prompt, una carpeta de documentos y un índice— que ejecuta el asistente general que la organización ya tiene (hoy, Gemini). La plataforma elige los documentos de cada consulta, compone el prompt con sus enlaces y registra el uso; una extensión de Chrome lo inserta al lado del asistente. |
| **Curación** | Rastreo del portal institucional, detección de contenido caducado o contradictorio, y selección de lo que entra al corpus. |
| **Registro de actividad IA** | El sitio donde las herramientas, también las de fuera (por API o MCP), declaran sus usos de IA: metadatos, nunca contenido. |
| **Utilidades** | Unir, dividir y optimizar PDF y anonimizar una hoja de cálculo sin subirlos a webs que no aseguran el RGPD. |

Cada área se abre con un **módulo concedido**, no con un rol; el detalle, en
`docs/ESPECIFICACIONES.md` §5.6.

La hoja de ruta pública, por temas y con estado y enlazada a las *issues* y a los hitos, está en
[`ROADMAP.md`](ROADMAP.md), por temas y con estado.

A las dos líneas que más se prestan a malentendidos las define tanto lo que hacen como lo que
deliberadamente no hacen:

- **Automatización gobernada** (construida y en producción). No un cliente de ejecución local:
  los agentes de propósito general ya ejecutan en el puesto de trabajo mejor de lo que lo haría un
  cliente propio. Lo que la plataforma aporta es **saber qué automatizaciones circulan** —el
  catálogo de funciones, las de origen externo, el registro de actividad y la anonimización— y
  los agentes de unidad sobre el asistente general.
- **Trámites asistidos con IA** (previsto, sin código). No un gestor de expedientes: las
  administraciones ya tienen uno, y es la fuente de verdad del procedimiento. Lo que falta son
  **trámites** —baremación, informe de fase, resolución— que se crean a mano o los crea el gestor
  por API, y cuyo resultado vuelve al expediente. La plataforma no cambia nunca el estado del
  procedimiento. Que no esté escrito no es un retraso: **qué tiene que hacer exactamente lo
  definen un despliegue real y una necesidad identificada**, y escribirlo antes sería adivinarlo.

`server/app/modules/automation/` no es el módulo de Automatización: son cinco ficheros de
infraestructura (estrategias de extracción) que consume Informes. El catálogo de funciones vive en
`server/app/modules/redaccion/`.

La regla que ordena el diseño técnico: **el servidor decide, el cliente pinta**. El frontend no
calcula qué acciones están permitidas, ni conoce a priori los campos de un formulario; los recibe.
Ver `docs/Arquitectura.md`.

## Dos modos de despliegue

El mismo código sirve a los dos, y esa es una restricción de arquitectura, no una opción:

- **Cloud-only** — todo corre en el servidor del proveedor; los datos se anonimizan antes de
  llegar al modelo.
- **Edge + Cloud** — la lógica que toca datos del cliente (RAG, grafos, ingesta, expedientes)
  corre **dentro de la nube de la institución**; el cloud sólo guarda configuración y métricas
  anonimizadas.

La frontera se sostiene con dos bases ORM separadas y una clasificación explícita de routers y
módulos, con tests que fallan si se cruza. Detalle en `AGENTS.md` §Frontera Edge-Cloud.

## Stack

Python 3.13 con **uv** · FastAPI · LangGraph · PostgreSQL 16 + pgvector · React + TypeScript +
Vite · i18next (`ca` / `es` / `en`) · Alembic · pytest + vitest.

## Arrancar en local

Requisitos: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node 20+. `.env.example` documenta
cada variable para quien prefiera rellenarlas a mano.

```bash
scripts/generate_env.sh              # genera .env, server/.env y frontend/.env con secretos
docker compose up -d postgres        # el servicio se llama postgres, no db
cd server; uv sync --extra shared    # añade --extra local-models si quieres los modelos en tu máquina
uv run alembic upgrade head
cd ..                                # el backend arranca DESDE LA RAÍZ, ver la nota de abajo
uv run --project server uvicorn server.app.main:app --port 8000
```

> **Desde la raíz, y con `server.app.main:app`.** La aplicación importa `server.*` en absoluto,
> así que necesita la raíz del repositorio en el camino de importación; desde `server/` falla con
> `ModuleNotFoundError: No module named 'server'`. Es el mismo módulo y el mismo directorio que
> usa la imagen de producción (`Dockerfile`), a propósito: dos formas de arrancar la misma
> aplicación es cómo una se queda atrás sin que nadie lo note.

Y el frontend, en otra terminal:

```bash
cd frontend; npm install
npm run generate:api                      # obligatorio en un clon nuevo: el cliente no se versiona
npm run dev                               # http://localhost:5173
```

`npm run generate:api` necesita el `openapi.json` que exporta el backend
(`cd server; uv run python export_openapi.py`); sin ese paso, `npm run dev` falla con veinte
«Cannot find module `@/shared/api/generated/…`». Es lo que cuenta «El contrato es la fuente de
verdad», más abajo.

En Windows, `arranque.bat` levanta el backend y el frontend de una vez — pero no genera el
cliente, que se hace una sola vez.

**Embeddings: en tu máquina o por API.** `--extra local-models` instala `torch` y BGE-M3, que es
lo que permite que el texto no salga de la institución — y son cientos de megas y un arranque de
varios minutos la primera vez, mientras carga los modelos; hasta que el servidor no escriba
`Application startup complete`, no responde. Sin ese extra el arranque es inmediato y los
embeddings se configuran contra un proveedor por API. **Cuál se usa lo decide la configuración, no
la instalación**: lo que decide el extra es si la pila local está disponible.

Esto de arriba es el camino corto. La instalación completa —incluido `scripts/setup.sh`, que
levanta el conjunto en un paso, y el interruptor de modelos locales en el despliegue— está en
[`docs/INSTALACION.md`](docs/INSTALACION.md).

## Tests

```bash
cd server;   uv run pytest tests          # desde Git Bash, no PowerShell
cd frontend; npm test
```

El detalle de por qué Git Bash, y qué subconjunto corresponde a cada momento, está en
`AGENTS.md`. **TDD es obligatorio**: el test va antes del código.

## El contrato es la fuente de verdad

`openapi.json` lo genera el servidor y el cliente TypeScript se deriva de él con Orval. No se
escribe a mano:

```bash
cd server;   uv run python export_openapi.py
cd frontend; npm run generate:api
```

## Dónde está cada cosa

```
server/                 el backend FastAPI y **la suite**: `server/tests/`
server/app/modules/     agents_hub · agentes · automation · curation · redaccion · utilidades
server/app/core/        servicios compartidos: LLM gateway, auth, tenancy, storage
frontend/src/           admin · agentes · automatizacion · curation · redaccion · utilidades · widget
extension/              la extensión de Chrome de los agentes de unidad, que se carga tal cual
mcp_server/             servidor MCP, stdio y remoto
shared/                 tipos y contratos compartidos (`automatia_shared`)
services/               microservicios aislados: `script_sandbox`
docs/                   arquitectura, decisiones, manuales, casos guía
planificacion/          plan de desarrollo, cursor del trabajo e historial
pruebas_manuales/       guiones .bat de lo que sólo puede juzgar una persona
```

**No hay proyecto Python en la raíz.** Los proyectos uv son cuatro —`server/`, `shared/`,
`mcp_server/` y `services/script_sandbox/`—, y cada comando se lanza con `--project` o desde su
directorio. CI, el despliegue y el `Dockerfile` trabajan con `server/pyproject.toml`.

## Documentación

- `docs/ESPECIFICACIONES.md` — **qué garantiza el sistema, capacidad por capacidad**, dónde se
  hace cumplir cada garantía y qué la demuestra. Es el documento para leer primero si vas a
  escribir código. Lo vigila un test: si algo de ahí deja de ser verdad, la suite se pone roja.
- `docs/PRESENTACION_PROYECTO.md` — qué hace la plataforma, qué está construido y verificado, y
  qué está previsto. Es el documento para leer primero si vienes de fuera.
- `docs/Arquitectura.md` — cómo está construida: los módulos que existen, las dos fronteras
  —cloud/edge y organización—, los datos, la recuperación y el despliegue.
- `docs/INSTALACION.md` — de clonar a un sistema que responde, con la elección de modelos
  locales o por API y lo que cuesta cada una. Amplía el «Arrancar en local» de aquí arriba.
- `docs/GUIA_DE_USO.md` — qué hace cada rol con la plataforma ya instalada: del alta de una
  organización a un asistente publicado, un informe aprobado o un portal curado.
- `docs/MARCO_GOBERNANZA_IA.md` — gobernanza, trazabilidad y protección de datos.
- `docs/LICENCIA_ES.md` — la AGPL explicada en español: qué permite, qué obliga y qué no, y qué
  significa para un pliego.
- `CONTRIBUTING.md` — cómo se trabaja aquí.
- `CODE_OF_CONDUCT.md` — qué se espera de quien participa, y a dónde se escribe cuando algo se
  incumple. Se aplica igual a quien mantiene el proyecto.
- `AGENTS.md` — reglas duras para agentes de programación, y de paso el contrato de estilo
  del proyecto. Vale para cualquier agente, no solo para Claude Code: el `CLAUDE.md` de la raíz
  es un fichero de tres líneas que importa este, porque Claude Code busca ese nombre por
  convención.
- `planificacion/PROJECT_STATE.md` — dónde está el desarrollo ahora mismo.

## Estado

**Esto es un proyecto experimental, y conviene leerlo antes de planificar nada con él.** Se
publica para que pueda instalarse y probarse, no como un producto sobre el que montar un servicio.
La **instalación de referencia** es la de la Universitat Jaume I, que es donde se despliega en
continuo y donde aparecen los fallos primero.

La versión lo dice: el proyecto está en `0.x` **a propósito**, y ahí se queda. En *semantic
versioning* eso significa que cualquier cosa puede romperse entre versiones, que es lo honesto
cuando no hay compromiso de compatibilidad ni de soporte. Se etiqueta **por acontecimiento y no
por calendario**: no hay cadencia prometida. El esquema completo está en
[`docs/VERSIONADO.md`](docs/VERSIONADO.md), y a un despliegue en marcha se le puede preguntar
—sin credencial— en `GET /api/v1/instancia`.

Numerar sin prometer soporte no es una contradicción: el número es **descripción, no promesa**.
Sirve para que quien instale sepa qué ejecuta y para que un informe de fallo sea comprobable. Lo
que la Universitat hace y lo que no está más abajo, en «Qué no acompaña a la publicación».

Está en desarrollo activo, y todo lo que queda en el árbol es código vivo.

Conviene conocer un límite antes de planificar sobre ella: **la plataforma no ejecuta nada en la
máquina de quien la usa**. No hay agente RPA, ni vigilancia de carpetas, correo o web, ni
programador de flujos locales, y no está previsto que los haya: los agentes de propósito general
ya ejecutan en el puesto de trabajo, y lo que esta plataforma aporta es la gobernanza de lo que
hacen —registro, anonimización, evidencia de supervisión—.

## Gobernanza: un principal y tantos forks como organizaciones

Este repositorio es el **principal** (*upstream*): aquí se decide la dirección del proyecto y aquí
se mantiene su carácter multiorganización.

Cada organización que despliegue la plataforma —una universidad, una diputación, un ayuntamiento—
trabaja sobre **su propio fork**: ahí van su despliegue, su configuración y los desarrollos que
responden a necesidades suyas. Lo que se pueda generalizar **se pide** que suba al principal por
*pull request*.

La regla vale igual para todas, **incluida la Universitat Jaume I**, donde nació el proyecto: su
desarrollo institucional entra como aportación, no como dirección. Por eso este documento no nombra
ningún fork en particular; no hay uno privilegiado.

La razón es la que da sentido al proyecto: está destinado a varias administraciones, no a una. Si
las necesidades de una institución entraran directamente en el principal, en poco tiempo el
principal *sería* el sistema de esa institución, y el resto heredaría decisiones tomadas para un
contexto que no es el suyo. Con fork y *pull request*, lo específico se queda donde es específico y
sólo sube al principal lo que sirve a todos.

### Lo que obliga la licencia y lo que pide el proyecto

Conviene no confundirlos, porque son cosas de naturaleza distinta y sólo una es exigible.

| | |
|---|---|
| **La licencia obliga a** | Dar el código fuente de **tu versión** a **los usuarios de tu despliegue**, si la has modificado y la ofreces por red (§13). Y a distribuirla bajo AGPL, con su fuente, si la distribuyes (§5 y §6). |
| **La licencia NO obliga a** | Enviar nada al principal. **Ningún copyleft obliga a contribuir aguas arriba**, ni la AGPL ni la GPL. Tampoco a publicar al mundo: la obligación es frente a los usuarios de esa instancia. |
| **El proyecto pide** | Que lo generalizable llegue por *pull request*. Es una **convención de gobernanza**, no una cláusula. |

El modelo funciona igual, pero por otra vía: la licencia garantiza que ninguna mejora quede cerrada
y que el principal **pueda** incorporarla legalmente; el *pull request* es lo que evita tener que ir
a buscarla. La licencia asegura la posibilidad, la convención asegura la comodidad — y conviene no
confiar en la segunda como si fuera la primera.

Las contribuciones al principal exigen **DCO** (*Developer Certificate of Origin* 1.1): una línea
`Signed-off-by` en cada commit, que `git commit -s` añade sola. Certifica que tienes derecho a
aportar el código; **no cede derechos**, conservas tu copyright. Texto íntegro en `DCO`.

El detalle operativo —qué se acepta como contribución y qué no, cómo se prepara— está en
`CONTRIBUTING.md`.

## Licencia, titularidad y procedencia

Copyright © 2026 **Universitat Jaume I de Castelló**  
Desarrollado en el grupo de investigación **INNOVAP** — Derecho Público e Innovación (Universitat Jaume I)  
Autor: **Modesto Fabra** — `fabra@uji.es`

La titularidad corresponde a la UJI, que es la persona jurídica. **INNOVAP** consta como
procedencia porque no es un dato accesorio: la aplicación nace de actividad investigadora, y de ahí
viene su vocación multiorganización. El desarrollo que la universidad realice sobre ella no cambia
ese origen; entra como aportación al proyecto de software libre.

Este programa se distribuye bajo la **GNU Affero General Public License v3.0 o posterior**
(`AGPL-3.0-or-later`). El texto completo está en `LICENSE`, íntegro y sin modificar: la propia
licencia permite copiarla literalmente pero no alterarla, así que la procedencia y el propósito se
declaran aquí y no dentro de ella.

**Una sola licencia.** El programa se distribuye únicamente bajo AGPL, y lo que se contrata son
**servicios**, no licencias. Si lees «dual-license» en algún documento de `planificacion/`, es una
posibilidad que la titularidad única permite y que **no se ha ejercido** — no un segundo régimen
en vigor.

Para quien tenga que decidir si su administración puede usar o desplegar esto, `docs/LICENCIA_ES.md`
explica en español qué permite la licencia, qué obliga, **qué no obliga** y qué significa para un
pliego. Es un documento informativo y lo dice: no es una traducción de la licencia, porque la FSF no
aprueba traducciones y dos textos que dicen cosas parecidas acaban diciendo cosas distintas. El
único texto vinculante es `LICENSE`.

> This program is free software: you can redistribute it and/or modify it under the terms of the
> GNU Affero General Public License as published by the Free Software Foundation, either version 3
> of the License, or (at your option) any later version.
>
> This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
> without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
> GNU Affero General Public License for more details.
>
> You should have received a copy of the GNU Affero General Public License along with this program.
> If not, see <https://www.gnu.org/licenses/>.

### Qué no acompaña a la publicación

La Universitat Jaume I **publica este código; no presta servicio sobre él**. Conviene decirlo aquí
y no dejarlo a la lectura de los §15 y §16 de la licencia, porque son cosas distintas: aquéllos
excluyen la garantía, y esto describe lo que la institución hace y lo que no. No hay soporte, ni
mantenimiento comprometido, ni despliegue para terceros, ni atención de incidencias de instalaciones
ajenas, ni plazo de respuesta para lo que llegue. **Es el régimen con el que la Universitat publica
su software libre**, y no una reserva de este proyecto en particular.

**Quien despliega es responsable de su instancia** (`SECURITY.md`). Si una organización necesita
garantías, plazos o acompañamiento, la vía es contratar **servicios** —despliegue, adaptación,
soporte, formación, corpus— con un proveedor: la licencia lo permite expresamente, y
`docs/LICENCIA_ES.md` explica cómo encaja eso en una compra pública.

Lo que sí hay: el repositorio acepta *issues* y *pull requests*, y `CONTRIBUTING.md` dice qué se
acepta y cómo se prepara. Que se lean y se atiendan es la voluntad del proyecto, no un compromiso
de servicio —y la diferencia importa el día que alguien planifique contando con ello—.

### Por qué AGPL y no GPL

Por el §13. Quien despliegue una versión modificada de esta plataforma **como servicio en red**
tiene que ofrecer el código fuente de esa versión a quien la use. Para software de administración
pública servido por web, esa es la diferencia que importa: sin ella, una modificación puede
servirse a la ciudadanía sin devolver nada. Y siendo el destinatario otras administraciones, es
también lo que impide que una mejora pagada con fondos públicos quede cerrada.

### La obligación del §13 sobre cada despliegue

**Está cumplida, y consta de dos piezas.** El servidor lo publica: `GET /api/v1/instancia`
devuelve el `SOURCE_URL` que configure quien despliega, es **público y sin credencial** a
propósito —la obligación es frente a quien usa el programa, incluida la ciudadanía que escribe en
el widget— y vacío significa «no hay enlace», que es lo correcto para quien despliega sin
modificar. **Y se ve**: el componente `EnlaceAlFuente` lo pinta en el pie del panel y en el pie
del widget embebido, con tests de los dos caminos —con enlace y sin él—.

`SOURCE_URL` llega al contenedor desde una variable del repositorio, por
`deploy/vm/docker-compose.vm.yml`. Ese paso es la parte que se olvida: sin él, el endpoint
responde vacío siempre y nada falla, que es el modo silencioso de incumplir esta obligación.

Las tres condiciones, que no son opcionales:

- **Va en la interfaz del despliegue**, no en este README. La obligación es de quien ejecuta la
  versión modificada, frente a los usuarios de **esa instancia**.
- **Apunta al fuente de esa versión** —el fork, en el commit desplegado—, no al principal. El §13
  pide el *Corresponding Source*, no «el proyecto». Por eso tiene que ser **configuración**
  (`SOURCE_URL` o equivalente) y no una URL fija en el código: fijarla al principal haría que
  cualquier despliegue modificado incumpliera.
- **Tiene que verse donde están los usuarios**, y eso incluye el **widget público embebido**: la
  ciudadanía que usa el chatbot también son usuarios interactuando remotamente. Es el caso que se
  olvida.

El §13 se activa **si se modifica** el programa: quien despliegue el código tal cual no queda
sujeto a esta obligación concreta, aunque enlazar el fuente sigue siendo lo razonable.
