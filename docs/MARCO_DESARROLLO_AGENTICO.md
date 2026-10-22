# Marco de desarrollo asistido por agentes

> **Qué es este documento.** El método con el que se desarrolla Gov Gen AI Platform, escrito para
> que otros proyectos del Teclab puedan adoptarlo. No es una propuesta teórica: es lo que ha quedado
> tras varios meses de ensayo y error en un proyecto real, contrastado con lo que hay publicado.
>
> **Escrito el 2026-09-03, revisado el 2026-09-23**, cuando el plan **empezó** a migrar de una
> lista de prompts a *issues* y una hoja de ruta. La migración está a medias a propósito y §4.7
> dice exactamente por dónde va. **Ámbito**: desarrollo de software con agentes de programación
> bajo supervisión humana.
>
> **Quien dirige este desarrollo es jurista y no sabe programar**, y eso es la condición del
> experimento y no un dato de autoría: §1.5.

---

## 0. Cómo leer este documento

Está escrito para tres lectores distintos. Conviene saber cuál eres:

| Si eres… | Lee |
|---|---|
| Quien decide si adoptar el método | §1 (por qué merece la pena), §2 (los principios), §10 (la comparación) |
| Quien va a trabajar así | §3 a §7, y sobre todo **§9, los errores que ya pagamos** |
| **Un agente que tiene que montar los documentos de un proyecto nuevo** | §11, que lleva el orden, el prompt de arranque y las plantillas |

**Tres marcas de credibilidad.** No todo lo que dice este documento vale lo mismo, y cada
afirmación relevante lleva una etiqueta que dice cuánto crédito darle:

- **[Evidencia]** — hay un estudio publicado detrás, y se cita.
- **[Convención]** — es práctica establecida o estándar emergente en la industria, sin evidencia
  cuantitativa.
- **[n=1]** — es la experiencia de este proyecto, y de ninguno más. *n=1* es la forma breve de
  decir «una sola muestra»: puede ser un acierto o una casualidad, y presentarlo como método
  validado sería un mal servicio a quien lo lea.

La mayoría del marco es **[n=1]**. Se dice desde el principio porque es lo que permite a otro
equipo decidir qué adoptar tal cual y qué tratar como hipótesis.

**Cuatro términos que se usan en todo el documento:**

| Término | Qué significa aquí |
|---|---|
| **Prompt** | Una instrucción de trabajo para el agente, escrita con sus tests y su criterio de cierre. Es la unidad mínima del plan; hoy se escribe en el cuerpo de una *issue* (§4.7) |
| **Bloque** | Un conjunto de pasos que entrega algo utilizable. Es la unidad de interacción con el humano, y lo sigue siendo con *issues* |
| **Estado** | Lo que sitúa el desarrollo dentro del conjunto del plan: qué está hecho, qué está en curso y qué falta. El método estándar son las *issues* y los hitos de la forja; este proyecto empezó con un documento de planificación con un **cursor**, que sólo funciona con un único escritor (§4.4) |
| **Guardarraíl** | Un test de la suite que falla cuando un documento del proyecto deja de ser verdad |

---

## 1. Por qué merece la pena generalizarlo, y qué dice la evidencia

### 1.1 La tesis

Con agentes de programación, **el método importa más que la herramienta**. Un equipo que ya trabaja
con tests, revisión y trazabilidad va a ir mejor con agentes; un equipo que no, va a producir más
deuda y más rápido. El método que describe este documento es la parte que se puede transferir de un
proyecto a otro: los principios, el modelo de permisos, el ciclo de trabajo y los mecanismos que
mantienen la documentación honesta.

Cuatro razones para generalizarlo en lugar de dejar que cada proyecto improvise el suyo:

1. **Las piezas no dependen del dominio.** El modelo de permisos, el ciclo TDD, el registro de
   decisiones y los guardarraíles son iguales para un asistente normativo que para un gestor de
   expedientes. Lo que cambia entre proyectos son las decisiones de arquitectura, y el documento
   dice explícitamente cuáles no copiar (§11.3).
2. **El coste de adopción es bajo y está medido.** Los documentos de gobierno de un proyecto nuevo
   se montan con un prompt que este documento incluye (§11.2), en un orden que evita escribir lo
   que luego hay que tirar.
3. **Los errores catalogados son generales, no nuestros.** La sección §9 recoge los fallos que ya
   pagamos, y ninguno es específico del proyecto: son la forma en que fallan los agentes, los
   tests y la documentación en cualquier equipo. Empezar sabiéndolos es la ventaja más barata que
   se puede tener.
4. **La evidencia publicada apunta en la misma dirección.** Lo que sigue.

### 1.2 El dato del que hay que partir

En julio de 2025, METR publicó un **ensayo controlado aleatorizado** con 16 desarrolladores
experimentados y 246 tareas reales en sus propios repositorios (proyectos de más de 22.000
estrellas y más de un millón de líneas). Con acceso a herramientas de IA fueron **un 19 % más
lentos**, y creían haber sido un 20 % más rápidos. Antes de empezar habían pronosticado un 24 % de
mejora. **[Evidencia]**

El estudio se cita mucho y casi siempre mal, en las dos direcciones. Dos matices lo hacen
utilizable:

1. **La misma organización estima que un año después esos desarrolladores serían un 18 % más
   rápidos.** El dato de 2025 no es una ley. Es una foto de unas herramientas concretas en un
   momento concreto. **[Evidencia]**
2. **La brecha entre percepción y realidad fue de casi 40 puntos.** Eso sí es estructural y no
   depende del modelo: quien usa un agente no sabe, por introspección, si le está yendo bien.

De ahí sale el primer requisito de cualquier método serio en este terreno: **medir, no sentir**.

### 1.3 La IA como amplificador

El informe DORA de 2025 sobre desarrollo asistido por IA, con cerca de 5.000 profesionales, más de
100 horas de datos cualitativos y una adopción del 90 %, concluye que la IA actúa como
**amplificador**: multiplica las fortalezas de una organización y también sus debilidades. Su frase
resumen es la mejor justificación de este documento: *«velocidad sin estabilidad es caos
acelerado»*. **[Evidencia]**

**El agente no arregla el método; lo revela.** Esa es la razón de fondo para tener un método antes
de tener agentes.

### 1.4 Dónde decide el humano

El informe de tendencias de codificación agéntica de Anthropic de 2026 encuentra que los humanos
toman alrededor del **70 % de las decisiones de planificación** y solo cerca del **20 % de las
decisiones de ejecución**. **[Evidencia]**

Ese reparto describe el equilibrio que busca este marco, y explica por qué el método se concentra
en la planificación y en las puertas de cierre en lugar de vigilar cada comando.

En la industria circulan al menos dos taxonomías de autonomía para agentes: una de cinco niveles al
estilo de la conducción autónoma, y otra de seis con controles alineados al riesgo. Coinciden en un
punto: **el nivel máximo no es apropiado para producción hoy**, porque los mecanismos de control
que lo harían seguro no existen todavía. **[Convención]**

### 1.5 De dónde sale esto, y por qué importa decirlo

**Quien dirige este desarrollo es jurista y no sabe programar.** No es una anécdota de autoría: es
la condición del experimento, y conviene ponerla delante porque cambia cómo hay que leer todo lo
que sigue.

El proyecto nació con tres preguntas a la vez:

1. **¿Puede construir software quien conoce una materia y no sabe programar?** Es la promesa que
   se le atribuye a los agentes, y casi nunca se pone a prueba en condiciones reales: con una
   institución detrás, datos de verdad, y la obligación de que lo construido siga funcionando
   dentro de dos años.
2. **¿Se puede gobernar la IA en la administración pública con garantías demostrables?** No
   declaradas en un documento, sino incorporadas al sistema y comprobadas por tests. Es lo que la
   plataforma hace, y el método es lo que permitió hacerlo.
3. **¿Qué método hace falta para las dos cosas a la vez?** Ninguna de las dos se resuelve con la
   herramienta. La primera necesita salvaguardas que suplan lo que quien dirige no puede revisar
   línea a línea; la segunda, que esas salvaguardas dejen evidencia.

**Esto es lo que convierte a este documento en algo más que un método más**, y también lo que lo
hace más frágil: es **[n=1]** en el sentido fuerte —una persona, un proyecto, un dominio—, y quien
lo lea debe tratarlo como hipótesis contrastable, no como resultado.

**La consecuencia práctica, y es la tesis de §1.1 vista del revés.** Si el método importa más que
la herramienta, entonces **la falta de conocimiento de programación no se compensa con un modelo
mejor, sino con mecanismos que hagan visible lo que uno no sabe mirar**. De ahí salen, y no de una
preferencia estética, las tres cosas que este marco repite: que nada se reporte sin medirlo (P2),
que la documentación se ponga roja cuando miente (P6), y que §9 catalogue los errores en vez de
esconderlos. Quien no puede auditar el código **tiene que poder auditar el proceso**.

Y de ahí sale también que el método haya cambiado con el tiempo, que es lo que cuenta §4.7.

---

## 2. Principios

Seis, y ordenados: cuando dos chocan, gana el de arriba.

### P1 — Agentes supervisados, no autónomos

El agente ejecuta, mide y demuestra. **Las decisiones que cambian el producto son humanas.** No es
desconfianza en el modelo: una decisión de diseño mal tomada se paga durante años, y quien la paga
es quien mantiene el sistema.

En la práctica, esto se concreta en **cuatro causas, y solo cuatro, para interrumpir al humano** a
mitad de trabajo (§5.3). Con menos, el agente se atasca. Con más, la supervisión se vuelve ruido
que se ignora, que es la forma habitual en que muere una barrera.

### P2 — Nada se reporta sin medirlo

Si una cifra no se ha medido, no se presenta como medida. Si un test no se ha ejecutado, no se dice
que pasa. Si algo se verificó en un navegador, se dice **con qué evidencia**: qué dirección, qué
texto se encontró, qué decía la consola.

Es el principio que la brecha de percepción de METR obliga a tener. **[Evidencia]**

### P3 — Lo determinista antes que el modelo

Si algo se puede calcular, se calcula. El modelo se reserva para lo que solo él puede hacer:
redactar, valorar, interpretar lenguaje. Una tabla de datos la produce el código; la valoración de
esa tabla, el modelo, y sujeta a aprobación humana.

### P4 — Una sola fuente de verdad por cosa

Cada hecho vive en un sitio. Los demás documentos **apuntan** a él, no lo copian. Dos documentos que
dicen lo mismo acaban divergiendo, y el día que divergen los dos mienten, porque ya no se sabe cuál
tiene razón.

### P5 — El *por qué* se escribe, no solo el *qué*

El *qué* está en el código. Lo que se pierde es por qué se descartó la otra opción, y eso se paga
cuando alguien la reimplementa de buena fe seis meses después. Según el alcance, el *por qué* va a
uno de tres sitios: el **comentario del código** si es local, el **historial** si es de un paso del
plan, y el **registro de decisiones** si condiciona al resto (§4).

### P6 — Lo que hay que mantener al día se pone rojo cuando miente

Un documento que envejece es peor que no tenerlo, porque **miente con autoridad**. Todo documento
que se pueda comprobar mecánicamente se comprueba con un test de la suite (§6).

---

## 3. El modelo de permisos: qué se autoacepta y qué no

Es la sección más transferible del documento, porque se puede copiar casi literalmente.

### 3.1 La forma: tres cubos y una guarda

Los agentes de programación actuales permiten declarar permisos en tres cubos: **permitir** (se
ejecuta sin preguntar), **preguntar** (se eleva al humano) y **denegar** (no se ejecuta nunca).
Sobre eso se añade un **hook**: un programa que inspecciona cada comando antes de ejecutarlo y
decide en qué cubo cae. Hace falta porque los patrones de texto no bastan: `rm -rf` puede ser
legítimo dentro del directorio de trabajo y catastrófico fuera de él.

Esto coincide con lo que la literatura sobre **supervisión humana graduada** en generación de
código recomienda: la intensidad de la supervisión escala con el riesgo, y los mecanismos concretos
son puertas de revisión, **matrices de permisos**, registros de auditoría y despliegue por etapas.
**[Evidencia]**

### 3.2 El criterio: tres familias suben siempre al humano

La guarda clasifica cada comando y lo eleva si cae en una de estas tres familias. Todo lo demás es
trabajo normal de desarrollo y se aprueba solo. Este criterio es el corazón del modelo. **[n=1]**

| Familia | Qué incluye |
|---|---|
| **A. Sistema operativo** | Particiones, arranque, servicios, registro, cuentas locales, firewall, tareas programadas, ACL, apagado, elevación, instalación de software, ejecución de código descargado |
| **B. Borrado fuera de las raíces permitidas** | Cualquier borrado fuera del directorio de trabajo y del temporal |
| **C. Pérdida irreversible de datos o de historial** | `git push --force`, poda de volúmenes, `DROP DATABASE`, `git clean -xdf` |

Las tres comparten una propiedad: **no se pueden deshacer con `git revert`**. Lo que se puede
deshacer con git no necesita permiso; lo que no, siempre.

### 3.3 Lo que sí se autoacepta

La lista es deliberadamente amplia, y es lo que hace viable el método. Si cada comando pide permiso,
el humano deja de leer y aprueba en bloque, que es peor que no preguntar.

```jsonc
// Se ejecuta sin preguntar
"Read(*)", "Edit(*)", "Write(*)", "Glob", "Grep",
"Bash(git *)",            // incluido commit; el force-push lo captura el cubo de preguntar
"Bash(uv *)",             // gestor de paquetes y ejecutor de Python
"Bash(npm *)", "Bash(npx *)", "Bash(node *)",
"Bash(pytest *)", "Bash(alembic *)",   // tests y migraciones
"Bash(docker compose *)", "Bash(curl *)", "Bash(gh *)"
```

**Escribir ficheros del proyecto se autoacepta.** Es la decisión que más sorprende y la más
defendible: el trabajo del agente **es** escribir ficheros, todo está en git, y pedir permiso por
cada edición convierte la supervisión en un clic reflejo. Lo que se supervisa no es la edición,
sino el **cierre** (§5.2).

### 3.4 Lo que exige autorización, y lo que no se ejecuta nunca

```jsonc
// Preguntar (extracto)
"Bash(sudo *)", "Bash(shutdown *)", "Bash(diskpart *)", "Bash(reg *)",
"Bash(net user *)", "Bash(netsh *)", "Bash(schtasks *)", "Bash(icacls *)",
"Bash(winget *)", "Bash(msiexec *)",
"Bash(git push --force *)", "Bash(git clean -xdf*)",
"Bash(docker system prune*)", "Bash(docker volume rm*)",
"Edit(C:/Windows/**)", "Write(C:/Program Files/**)"

// Denegar: no se ejecuta ni preguntando
"Bash(rm -rf /)", "Bash(rm -rf ~)", "Bash(mkfs*)", "Bash(dd if=*)",
"PowerShell(Format-Volume*)", "PowerShell(Clear-Disk*)", "Bash(bcdedit *)"
```

**La diferencia entre «preguntar» y «denegar» es si existe un caso legítimo.** `git push --force`
lo tiene (reescribir un historial que contenía datos filtrados, algo que ocurrió en este proyecto),
así que pregunta. Formatear el disco del portátil no lo tiene nunca: se deniega, y así no hay un
momento de despiste en que se apruebe.

### 3.5 Las dos reglas que hacen que funcione

**La guarda tiene sus propios tests.** Un mecanismo de seguridad sin tests es una intención: nadie
sabe si sigue funcionando después de la siguiente refactorización.

**El agente no busca rodeos.** Si la guarda eleva algo, el agente se para y pregunta. Intentar otro
camino para conseguir el mismo efecto no es eficiencia: es violar el método.

---

## 4. Los documentos que rigen el desarrollo

Siete piezas, y cada una contesta **una** pregunta. La disciplina está en no dejar que uno
conteste la de otro (P4).

| Documento | Contesta | Cambia |
|---|---|---|
| **Reglas** (`AGENTS.md`) | ¿Cómo se trabaja aquí? ¿Qué está prohibido? | Rara vez |
| **Especificaciones** | ¿Qué **garantiza** el sistema? ¿Qué no puedo romper? | Cuando cambia una garantía |
| **Plan** (*issues* agrupadas en hitos; al principio, prompts TDD en ficheros) | ¿Qué falta, y en qué orden? | Al planificar |
| **Estado** (el de las *issues* y los hitos; al principio, un cursor) | ¿Dónde estamos dentro del plan? | Al abrir y al cerrar cada paso |
| **Historial** | ¿Por qué esto está así? ¿Qué se midió? | En cada paso, añadiendo |
| **Registro de decisiones** | ¿Por qué no se hizo de la otra manera? | Cuando se descarta una alternativa |
| **Contribución** | ¿Cómo aporto desde fuera? | Rara vez |

### 4.1 Las reglas: `AGENTS.md`

**Conviene usar el nombre estándar.** `AGENTS.md` se formalizó en agosto de 2025 con participación
de OpenAI, Google, Cursor, Factory y Sourcegraph. Pasó de unos 20.000 repositorios a más de 60.000
en diciembre de 2025, cuando la especificación se donó a la *Agentic AI Foundation* de la Linux
Foundation. Más de veinte herramientas lo leen. **[Convención, con adopción medida]**

Es Markdown plano sin esquema obligatorio. Si la herramienta busca otro nombre (Claude Code busca
`CLAUDE.md`), ese fichero debe tener tres líneas que **importen** el canónico, para que no haya dos
versiones que puedan divergir (P4).

> **Corto, imperativo y sin duplicar.** El estudio empírico sobre ficheros de contexto para
> agentes encuentra que **la longitud moderada funciona mejor** que la exhaustiva, que las
> instrucciones **explícitas** pesan más que los ejemplos implícitos, y que los agentes **se
> saltan** el contenido verboso y redundante. **[Evidencia]**
>
> De ahí salen tres reglas para el fichero. **Lo que se queda es el imperativo**, porque es lo que
> el agente lee antes de escribir código; el razonamiento largo va a documentos aparte que el
> fichero enlaza. **Cada regla lleva una cláusula de por qué**, y no más: una regla sin motivo se
> racionaliza y se salta, y una regla con un párrafo de motivo se lee por encima. Y **el fichero no
> repite lo que ya está en otro sitio**: la tentación constante es añadir «una frase más de
> contexto» junto a cada regla, y en meses eso convierte el fichero de reglas en una copia parcial
> del documento de metodología, con la divergencia asegurada.
>
> Un guardarraíl lo mantiene: comprueba que los punteros a otros documentos resuelven, que las
> reglas operativas siguen en el fichero y que su tamaño no crece por encima del listón fijado.
> El de este proyecto sigue siendo más largo de lo que la evidencia recomienda, así que la
> recomendación para quien empiece es no llegar ahí.

### 4.2 Las especificaciones: qué garantiza el sistema

Es el documento que contesta la pregunta que los planes no contestan. Un plan dice «haz X»; una
especificación dice **«el sistema garantiza Y»**. Solo lo segundo permite saber qué se puede cambiar
sin romper nada, y es lo primero que necesita quien llega de fuera a continuar un desarrollo.

Se organiza **por capacidad, no por orden de ejecución**, y cada capacidad sigue el mismo esqueleto.
El ejemplo es real y describe cómo el asistente decide en qué idioma responder:

```markdown
### 5.2 Política de lengua

**Qué hace.** Decide en qué lengua responde un asistente.

**Garantiza.** Tres modos y solo tres, configurables en cascada y validados al escribirse.
Un valor que no sea uno de los tres se rechaza con un error que enumera los modos válidos.

**Superficie.** El módulo que valida el modo, el endpoint que ofrece el catálogo al panel,
y dos columnas de configuración en cascada.

**Invariantes.** I3, I10.

**Madurez**: `construido`.

**Abierto.** Ningún despliegue monolingüe real lo ha usado todavía.
```

Su pieza central es una **tabla de invariantes**, cada uno con **dónde se hace cumplir**:

| # | Invariante | Se hace cumplir en |
|---|---|---|
| I1 | Una respuesta sin cita válida no se entrega | El validador de citas |
| I5 | Una lista de organizaciones vacía significa «ninguna», no «todas» | El módulo de tenencia |
| I9 | Un comentario no autoriza nada: declarar que un endpoint pertenece a un módulo obliga a exigirlo con código | Un test que recorre todos los endpoints |

**La columna derecha es lo que distingue un invariante de una intención.** Un invariante que solo
vive en un documento no obliga a nada.

**La madurez se expresa en cuatro palabras, no en un porcentaje**: `producción`, `construido`,
`parcial`, `previsto`. Un porcentaje hay que revisarlo; cuatro palabras, no. Y **la madurez la
mueve el despliegue**, no el cierre del trabajo. Esta última regla se aprendió por haberla
confundido. **[n=1]**

### 4.3 El plan: especificaciones en forma de prompts TDD

> **Ésta fue la primera forma del plan, y ya no es la única.** El trabajo **nuevo** de este
> proyecto vive en *issues* agrupadas en hitos, mientras la Fase 1 sigue ejecutándose con sus
> prompts: los dos conviven, y §4.7 dice por qué. El apartado se queda entero porque **lo que
> describe sigue valiendo** —es el andamiaje que permite dirigir un desarrollo sin saber
> programar— y los tres detalles del final son transferibles a una *issue* tal cual.

El trabajo pendiente se escribe como **instrucciones ejecutables**, agrupadas en bloques. Cada
prompt lleva su objetivo, sus tests mínimos enumerados y su verificación de cierre. El ejemplo es el
primer prompt del bloque que construyó la política de lengua del apartado anterior:

```markdown
### Prompt 1 (RED/GREEN) — Cablear el modo de lengua

**Modelo sugerido**: Sonnet — alcance cerrado: dos clases sobre un protocolo existente.

**Objetivo**: que el modo configurado decida la política de lengua que compone la factoría.

## Tests (mínimo 6)
- Modo «sin política»: el prompt final NO contiene «Responde en» y no se lanza segunda búsqueda.
- Modo «fijo en castellano» con pregunta en catalán: el prompt instruye responder en castellano.
- Modo «preferir la lengua de la pregunta»: comportamiento idéntico al actual (test de regresión).
- Un valor inventado se rechaza con error 422.

**Verificación**: suite del directorio verde, y una conversación real contra un asistente fijado
en castellano, preguntando en catalán y respondida en castellano (evidencia en el informe de cierre).
```

Tres detalles marcan la diferencia. **[n=1]**

- **Los tests van enumerados en el prompt.** Escribir «añade tests» produce tests que confirman lo
  que el código ya hace. Enumerarlos antes fija qué tiene que ser cierto.
- **Un test de regresión explícito** en todo prompt que cambie algo existente.
- **La verificación dice qué evidencia hace falta**, no «comprobar que funciona».

**Un fichero por bloque, desde el principio.** Un plan de fase entero en un solo fichero no se
puede revisar en una *pull request* ni comentar por línea, y crece hasta que nadie lo lee de
principio a fin. La unidad de fichero es la misma que la de ejecución: el bloque.

### 4.4 El estado y el historial

**El estado** sitúa el desarrollo dentro del conjunto de la planificación: qué está hecho, qué está
en curso, qué falta y en qué orden. Sin él, cada sesión empieza preguntando por dónde iba la
anterior, y la respuesta depende de la memoria de alguien.

**El método estándar son las *issues* y los hitos de la forja** —GitHub, GitLab o la que se use—.
**[Convención]** Cada unidad de trabajo es una *issue*, un bloque es un hito, y el estado no se
escribe a mano: se lee del propio sistema. Una *issue* está abierta o cerrada, tiene responsable,
se enlaza con el commit que la resuelve y se cierra sola al mezclar si el commit lo dice. Admite
varios escritores a la vez —personas y agentes—, permite trabajar en paralelo y es lo que ya
conoce quien llega de fuera. La hoja de ruta pública agrupa los hitos por temas.

**El cursor, que es como empezó este proyecto.** Es un documento de planificación con una marca de
«estamos aquí» que el agente mueve al cerrar cada paso. **Sólo tiene sentido cuando hay un único
escritor**: una persona dirigiendo un agente, sin nadie más tocando el plan. Con dos ya es un
cuello de botella. Dos sesiones editan el mismo fichero, nadie puede asignarse un paso, y el
fichero se queda atrás del código sin que nada lo avise. Aquí pasó tal cual: el cursor dejó de
actualizarse el 2026-09-26, mientras el trabajo seguía, y desde entonces el estado real está en
las *issues*. **[n=1]**

**La recomendación**: un proyecto nuevo sigue su estado con *issues* desde el primer bloque. El
cursor queda para quien desarrolla en solitario y sin forja, y aun así conviene saber que habrá que
migrar el día que llegue la segunda persona (§4.7).

**El historial** es una fila por paso cerrado, añadida arriba, con lo que solo se sabe después de
hacer el trabajo: la cifra que salió, el test que mentía, la alternativa que no funcionó. Es el
documento que ninguna herramienta del mercado ofrece y el que más agradece quien llega después.
**[n=1]**

Un ejemplo de fila real, traducido a lenguaje llano. Lo valioso es la parte negativa:

> Uno de los asistentes tenía **cero conversaciones registradas**, mientras que los otros tres
> tenían 33, 9 y 1. No es que se usara poco: todas sus conversaciones se perdían, y el usuario se
> quedaba esperando una respuesta que nunca terminaba. La causa era que el proveedor del modelo
> devolvía el texto en un formato que el código no esperaba. **Eran dos defectos, no uno**: el
> formato inesperado, y que el tramo de código que guardaba la conversación no tenía ninguna
> protección, así que fallaba en silencio. Era la tercera vez que el mismo problema mordía en un
> sitio distinto.

**El historial y el estado son cosas distintas.** El estado se consulta al arrancar cada sesión y
tiene que poder leerse de un vistazo; el historial crece una fila por paso y no tiene techo. Cuando
el estado era un cursor en un fichero, este proyecto los tuvo juntos, y la lectura del cursor
pagaba el peso del historial.

#### El plan y el estado viven en las *issues*; el historial no

La primera revisión externa (equipo Teclab, 2026-09-10) objetó que ellos gestionan plan e
historial con los *issues* del repositorio, y que así hay más paralelismo y un control más
flexible. **Para el plan y el estado tenían razón**, y el proyecto acabó haciéndolo así: un fichero
de plan es un cuello de botella de un solo escritor, mientras que las *issues* permiten varios
actores a la vez —personas y modelo—, asignación y trabajo en paralelo. El cursor deja de ser un
fichero y pasa a ser una vista: el estado de las *issues* de un hito.

**El historial y las decisiones son otra cosa, y sí van en el repositorio.** Cuatro razones, en
orden de peso:

1. **Viajan con el código.** `git clone` trae el historial; no trae los *issues*. Para un
   proyecto que se publica bajo AGPL y aspira a que otra administración lo recoja, el
   razonamiento tiene que estar dentro del repositorio. No es hipotético: este proyecto cambió de
   organización en GitHub el 2026-09-10 y va a borrar y recrear el repositorio para limpiar su
   historial — **los *issues* no sobreviven a eso y los commits sí**.
2. **La granularidad no encaja.** Una fila es un paso cerrado; un *issue* es una unidad de
   trabajo prevista. Lo más valioso del historial **no es una tarea, es un hallazgo**: nadie abre
   un *issue* para «la cifra que medí era un artefacto de mi propio instrumento». Abrirlo y
   cerrarlo en el acto es un cuaderno de laboratorio disfrazado de *issue*.
3. **El conocimiento negativo no tiene ciclo de vida.** Un *issue* nace abierto y muere cerrado;
   «probamos X y no funcionó» no tiene cierre, y cerrarlo lo entierra.
4. **El agente lee ficheros gratis.** Un fichero entra entero en el contexto; reconstruir lo
   aprendido a partir de cientos de *issues* cerradas cuesta llamadas y se pierde por el camino.

**El puente entre las dos cosas**: al cerrar un *issue*, el modelo escribe la fila del historial.
El *issue* dice **qué se pretendía**; la fila dice **qué se aprendió**. Son preguntas distintas,
y por eso ninguna sustituye a la otra.

### 4.5 El registro de decisiones (ADR)

Es el formato clásico de *Architecture Decision Record*: qué se decidió, cuándo, por qué, y **qué
quedó descartado**. **[Convención, establecida desde 2011]**

```markdown
# Decisión: <qué se decide, en una frase>

> **Fecha**: AAAA-MM-DD. **Estado**: aceptada | sustituida por … | revertida.
> **Origen**: <de dónde salió la pregunta>. **Afecta a**: <módulos>.
```

**El criterio de cuándo hace falta uno** evita los dos extremos, que nadie escriba ninguno o que se
escriba uno por cada corrección:

> Si dentro de un año alguien pudiera implementar **lo contrario** de buena fe, hace falta una
> decisión escrita. Si solo repetiría un error ya pagado, basta una fila del historial.

Y **una decisión no se edita para cambiarla**. Se escribe otra que la sustituya, y la vieja pasa a
`sustituida por…`. Borrar el razonamiento antiguo destruye la prueba de que la alternativa se
consideró.

### 4.6 Comparación con los marcos publicados

| | Spec Kit (GitHub) | Este marco |
|---|---|---|
| Principios no negociables | `constitution.md` | `AGENTS.md` |
| Qué construir | `spec.md` | Plan por prompts |
| Plan técnico | `plan.md` | Dentro de cada prompt |
| Tareas ordenadas | `tasks.md` | *Issues* e hitos (al principio, un cursor) |
| **Qué garantiza el sistema** | — | **Especificaciones** |
| **Por qué se hizo así** | — | **Historial + ADR** |
| **TDD obligatorio** | — | **Sí** |
| **Documentación con test** | — | **Guardarraíles (§6)** |

La forma coincide: hay convergencia real en la industria hacia «principios → qué → plan → tareas».
**[Convención]** Lo que este marco añade son las cuatro filas inferiores. De ellas, la que más
conviene defender ante otro equipo es **TDD obligatorio**, porque es la que hace que el resto sea
comprobable y no una declaración de intenciones.

### 4.7 El plan cambió de forma: de lista de prompts con cursor a *issues*

Este apartado existe porque el documento describiría un método que el proyecto ya no sigue. Y porque **la transición es probablemente lo más útil que hay aquí para otro equipo**: no la
foto final, sino qué la disparó y qué se conservó al cruzarla. **[n=1]**

**Se hizo por partes, a propósito**, que es el dato que más conviene no maquillar:

| Plan | Estado a 2026-10-22 |
|---|---|
| `Plan_TDD_Fase1.md` | El último plan escrito en prompts. Su cursor dejó de actualizarse el 2026-09-26; lo que quede pendiente de él se abre como *issue* cuando se retoma |
| `Plan_Contrato_OpenAPI.md` | Completo; no tiene cursor |
| Fases 2 y 3 | **Cerradas y sustituidas** por `ROADMAP.md` y los hitos de *issues*. No se ejecutarán como estaban escritas |

Así que lo honesto no es «migramos», sino **«migramos lo que aún no estaba en marcha, dejamos
correr lo que sí, y el cursor se quedó atrás solo»**. Reescribir la Fase 1 en *issues* sólo por
uniformidad habría costado trabajo sin comprar garantía, que es la misma razón por la que §11.3
dice qué no copiar.

**Lo que había.** Un documento de planificación por fase, partido en un fichero por bloque, con los
prompts TDD que describe §4.3. El cursor decía en qué prompt estábamos. Funcionó durante meses y
construyó casi todo lo que hoy está en producción.

**Lo que hay para lo nuevo.** Las *issues* de GitHub agrupadas en hitos, y una hoja de ruta pública
por temas. Se ejecutan **igual que un prompt** —RED → GREEN → REFACTOR, verificaciones de cierre,
un commit firmado por *issue*—; lo que cambia es dónde está escrito el alcance, y que al cerrar se
cierra la *issue* en vez de mover un cursor.

**Qué lo disparó, y son tres cosas que conviene distinguir:**

1. **Cambió la naturaleza del trabajo.** Un plan de prompts contesta «¿qué falta construir, y en
   qué orden?». Llega un momento en que la pregunta pasa a ser «¿qué ha aparecido que hay que
   arreglar?», y ahí una lista escrita por adelantado es el artefacto equivocado: los defectos no
   se planifican, se descubren. La señal fue concreta —empezaron a abrirse más *issues* de las que
   el plan preveía— y tardamos en leerla.
2. **Creció la competencia de quien dirige.** Al principio, escribir el trabajo como prompts con
   sus tests enumerados **era el andamiaje que permitía dirigir sin saber programar**: obligaba a
   decidir por adelantado qué tenía que ser cierto, que es una decisión de criterio y no de
   código. Con los meses, esa decisión se podía tomar ya sobre una *issue* bien escrita, sin
   redactar el prompt entero. El andamiaje dejó de hacer falta porque cumplió su función.
3. **Llegó gente de fuera.** Un plan en un fichero no se comenta por línea, no se asigna, no se
   cierra solo al desplegar y no lo entiende quien llega. Las *issues* son el estándar que esa
   gente ya conoce, y el coste de no usarlo lo paga siempre el que llega.
4. **Dejó de haber un solo escritor.** En cuanto trabajaron a la vez dos sesiones de agente sobre
   el mismo repositorio, el cursor se convirtió en un fichero que las dos tenían que editar. Es
   el límite que §4.4 describe, y fue el último empujón.

**Qué se conservó, que es la parte que importa.** Nada de lo que da garantías dependía del formato
del plan:

| Se conserva | Cambió |
|---|---|
| El **bloque** como unidad de interacción (§5.1) | Un bloque ya no es una lista de prompts: es un **hito** con sus *issues* |
| El bucle **RED → GREEN → REFACTOR** y el commit por paso | — |
| Los **tests escalonados** (§5.4) y la verificación en navegador (§5.5) | — |
| El **informe de cierre** (§5.6) | — |
| Los **guardarraíles** (§6) | — |
| El **historial** (§4.4) | — |
| El **registro de decisiones** (§4.5) | — |
| El **estado** (§4.4) | Lo daba el cursor; ahora lo da el de las *issues* y los hitos. El cursor de la Fase 1 queda como registro |

**La lección, dicha como hipótesis y no como resultado.** El andamiaje que necesita quien empieza
—prompts escritos con sus tests enumerados— **no es el mismo que necesita a los seis meses**, y
mantenerlo por inercia cuesta trabajo sin comprar garantía. Lo que no cambia son las salvaguardas:
si al migrar a *issues* se hubieran perdido los tests escalonados o los guardarraíles, la
transición habría sido un retroceso disfrazado de modernización.

**Y una consecuencia mecánica que costó once *issues* abiertas.** Con el plan en un fichero, un
paso cerrado se marcaba a mano. Con *issues*, cerrar es automático **sólo si aparece una palabra de
cierre** —`Closes`, `Fixes` o `Resolves` seguidas de `#N`— **en el cuerpo del commit o en el de la
*pull request***; un asunto `fix(#N):` no cierra nada. Durante un tiempo
la lista de *issues* anunció defectos ya resueltos y desplegados, que es justo lo primero que mira
quien llega. Lo arregla un guardarraíl en la integración continua, y es un buen ejemplo de la regla
general: **al cambiar de mecanismo hay que preguntarse qué hacía el anterior que el nuevo no hace
solo**.

---

## 5. El ciclo de trabajo

### 5.1 El bloque es la unidad de interacción

Un bloque es un conjunto de pasos que entrega algo utilizable: las *issues* de un hito, o en la
Fase 1 prompts con su cursor (§4.7). El concepto no cambia con el artefacto. Una vez arrancado, el
agente **no informa hasta cerrarlo** y no pide confirmación entre pasos.

Esto es lo que hace rentable el método, y encaja con el reparto que mide Anthropic: el humano en la
planificación, el agente en la ejecución. **[Evidencia]** Confirmar cada paso convierte al humano en
un cuello de botella que, además, deja de leer.

### 5.2 El bucle por paso

```
RED → GREEN → REFACTOR → verificaciones de cierre → actualizar el estado → un commit firmado
```

**Actualizar el estado** es que el commit cierre su *issue* —`Closes #N` en el cuerpo— y escribir
la fila del historial. Con un cursor era mover la marca al paso siguiente.

**Un commit por paso, firmado.** Es lo que hace reversible un bloque largo: si el paso 5 rompe lo
que hizo el 3, hay un punto exacto al que volver. Sin eso, un bloque de siete pasos es un solo
commit gigante que no se puede revertir a medias. De todo lo que se describe aquí, es una de las
prácticas que más ha servido. **[n=1]**

Las **verificaciones de cierre** son la supervisión real, y por eso los permisos pueden ser amplios
(§3.3): suite verde en los directorios tocados, migración aplicada, contrato regenerado si cambió
la API, código antiguo retirado y comprobado con una búsqueda que devuelve cero, y verificación en
navegador si el cambio toca la interfaz.

### 5.3 Cuándo interrumpir al humano, y cuándo no

**Solo por estas cuatro causas:**

1. **Operación de riesgo.** La detecta la guarda (§3). No se fuerza ni se busca un rodeo.
2. **Decisión de criterio.** Una ambigüedad que llevaría a productos distintos, una arquitectura
   que el plan no cierra, un alcance que excede el bloque.
3. **Fallo persistente.** Un test en rojo que no llega a verde. Se para y se reporta **con la
   salida real**.
4. **Prerrequisito externo ausente.** Base de datos apagada, credencial que falta.

**Y explícitamente no se interrumpe por** desviaciones entre el plan y el código real (se aplica la
interpretación más fiel, se registra como *desviación documentada* y se sigue), por fallos
preexistentes ya inventariados, ni por dudas de estilo que las reglas ya resuelven.

Enumerar las causas de **no** interrumpir es tan importante como enumerar las de sí. Sin esa lista,
el agente pregunta por todo y la supervisión se degrada a aprobación automática. **[n=1]**

### 5.4 Tests escalonados

**Antes de la tabla, el porqué, que no es el habitual.** Con un agente, el test deja de ser una
red de seguridad y pasa a ser **el contrato**. En desarrollo normal los tests te protegen de
romper cosas; con un agente son **la única forma de que «está hecho» sea falsable sin leerse cada
línea**. Por eso el plan se escribe como prompts TDD (§4.3): los criterios de aceptación son
ejecutables *antes* de que exista el código. Sin eso, «el agente dice que está terminado» no se
puede comprobar.

Y de ahí sale lo demás. Un agente ejecutará la suite entera después de cada cambio si le dejas:
una hora por paso y ninguna información nueva. Los tres niveles responden a **tres preguntas
distintas** —¿funciona lo que acabo de escribir?, ¿he roto a mis vecinos?, ¿he roto algo?— y por
eso cuestan lo que cuestan.

| Cuándo | Qué | Coste |
|---|---|---|
| Durante el paso | Solo el fichero de tests que se está escribiendo | segundos |
| Al cerrar el paso | Los directorios que toca, más el test de higiene de la suite | de segundos a un minuto |
| Al cerrar el bloque | La suite entera | de minutos a una hora |

Ejecutar la suite completa después de cada cambio no aporta información nueva y sí una hora de
espera. El test de higiene entra en el nivel intermedio porque tarda medio segundo y caza justo lo
que se escapa de un subconjunto: dobles de test mal puestos, creación de esquema sobre la base de
datos del desarrollador, imports a módulos que ya no existen.

### 5.5 Verificación en navegador por el propio agente

Si el trabajo toca la interfaz, **el agente lo comprueba él mismo en un navegador real** dentro del
bloque: navega, busca el texto, interactúa, y lee la consola y las peticiones de red en busca de
errores que los tests unitarios no ven.

Las **pruebas manuales humanas se reservan** para lo irreducible: credenciales reales, sistemas
externos que no se pueden simular, juicio sobre la identidad visual, lector de pantalla real, datos
personales. Y se entregan como un guion ejecutable, no como una lista de deseos.

No es cosmético. En este proyecto, la verificación en navegador ha encontrado defectos que la suite
no veía **y que no podía ver**: un error 500 en un inicio de sesión, un flujo que no terminaba
nunca, y un botón que decía «Editar» y lo que hacía era activar un asistente. **[n=1]**

### 5.6 El informe de cierre

Un solo mensaje con: los pasos cerrados y sus commits, las **cifras reales** de cada suite, las
migraciones aplicadas, qué se verificó en navegador y con qué evidencia, las desviaciones
documentadas, lo que queda pendiente, las pruebas manuales, y **una línea que dice qué cambió en las
especificaciones o por qué no cambió nada**.

Esa última línea es la que sostiene el mantenimiento de la documentación. **Obligar a afirmar la
omisión** convierte «me lo salté» en una frase que se puede revisar.

---

## 6. Guardarraíles: documentación que se pone roja

### 6.1 La idea

Todo documento que se pueda comprobar mecánicamente tiene un test en la suite que falla cuando el
documento deja de ser verdad. No es documentación *sobre* el código: es documentación **comprobada
por** el código.

Es la respuesta operativa a P6, y no aparece en ninguno de los marcos publicados. **[n=1]**

**En qué se concreta, porque la primera revisión externa preguntó justo esto (2026-09-10): no hay
ninguna infraestructura.** Un guardarraíl es **un fichero de test normal, en la suite normal**,
que en vez de comprobar código comprueba que un documento sigue siendo verdad: lee un `.md` —o un
YAML de integración continua, o el manifiesto de dependencias— y lo contrasta con el código o con
el sistema de ficheros. Nada más. Quien espere una herramienta aparte no la va a encontrar, y por
eso cuesta verlo: el mecanismo es tan pequeño que parece que falta algo.

### 6.2 Los cinco tipos que se usan

| Tipo | Qué comprueba | Ejemplo real |
|---|---|---|
| **Inventario completo** | Que el documento nombra **todo** lo que el código declara | Toda tabla de configuración está en el inventario de multitenencia con su ámbito |
| **Vocabulario sincronizado** | Que las listas del documento son las del código | Los modos de lengua del documento son los que el validador acepta |
| **Referencias vivas** | Que las rutas y ficheros que nombra existen | Las 35 rutas que cita la especificación |
| **Regla presente** | Que una regla no ha desaparecido del fichero de reglas | Que la regla de mantener la especificación sigue ahí **y conserva su condición** |
| **Clase de defecto** | Que un patrón que ya falló no vuelve | Que nadie lee la respuesta del modelo sin normalizarla antes |

### 6.3 La trampa: el guardarraíl que pasa en el vacío

**Es lo más importante de esta sección.** Un guardarraíl que recorre un directorio inexistente no
encuentra nada y, por tanto, **pasa en verde sin haber mirado nada**. Ocurrió en este proyecto: un
test que prohibía cierto patrón usaba una ruta mal calculada, y llevaba días en verde sin haber
comprobado una sola línea. Se descubrió por casualidad, al copiarlo para otro uso. Es el error más
peligroso del método. **[n=1]**

Es peor que un falso negativo normal porque **no hay ninguna cifra extraña que dé el aviso**. Un
verde no llama la atención de nadie.

Dos reglas lo evitan:

```python
# 1. La raíz se comprueba, no se supone.
RAIZ = Path(__file__).resolve().parents[3]
assert (RAIZ / "docs").is_dir(), f"la raíz no es la que se cree: {RAIZ}"

# 2. El test tiene que demostrar que sabe encontrar lo que busca:
#    se escribe primero contra el estado que SÍ tiene ocurrencias, y se ve rojo.
```

Y una práctica cierra el círculo: **sabotear el documento a propósito y ver el rojo** antes de dar
el guardarraíl por bueno. Un guardarraíl que solo se ha visto en verde no se ha visto.

### 6.4 Un guardarraíl completo, como plantilla

```python
"""El registro de decisiones no puede quedarse corto.

Una decisión escrita y no indexada es una decisión que nadie encuentra: quien venga detrás
implementará lo contrario de buena fe.
"""
RAIZ = Path(__file__).resolve().parents[3]
assert (RAIZ / "docs").is_dir(), f"la raíz no es la que se cree: {RAIZ}"


def _decisiones() -> list[Path]:
    encontradas = sorted((RAIZ / "docs").glob("DECISION_*.md"))
    assert encontradas, "no se ha encontrado ninguna: la ruta está mal y esto pasaría en vacío"
    return encontradas


@pytest.mark.parametrize("decision", _decisiones(), ids=lambda p: p.stem)
def test_should_be_listed_in_the_register(decision, registro):
    assert decision.name in registro, (
        f"`{decision.name}` no está en el registro. Una decisión escrita y no indexada es una "
        "decisión que nadie encuentra."
    )
```

Tres cosas a observar: el `assert` sobre la raíz, el `assert` de que la búsqueda encontró algo, y
que **el mensaje de error explica la consecuencia**, no solo el hecho. Quien se encuentre ese rojo
dentro de un año tiene que entender por qué importa.

---

## 7. Integración continua

### 7.1 Las puertas

La integración continua no es «que pasen los tests». Son puertas con propósito, y cada una existe
por algo que pasó:

| Puerta | Por qué |
|---|---|
| Lint | Corre **antes** de los tests: un import sin usar deja el trabajo en rojo sin que nada se ejecute |
| Dependencias con *lock* verificado | Instalar sin verificar vuelve a resolver en silencio, y un *lock* que no corresponde a su manifiesto no da ningún síntoma |
| Contrato regenerado y tipado | El cliente del frontend se genera a partir del contrato del backend; si no compila, el contrato se rompió |
| Suite completa | En **una sola invocación** |
| Puerta de control de acceso | Un subconjunto de tests de aislamiento que **bloquea el despliegue** |
| Puerta de regresión de calidad | Falla si una métrica baja más de un umbral respecto a una línea base versionada |
| Accesibilidad | Una base mínima que no puede empeorar |
| Certificado de origen (DCO) | Cada commit va firmado |

### 7.2 En la integración continua el paralelismo se apaga, a propósito

En local, los tests corren en paralelo por velocidad. **En la integración continua, no.** El
paralelismo reparte los tests entre procesos y eso **esconde el estado que se filtra entre tests**
(un doble asignado a una clase, un objeto global contaminado), que es justo lo que se quiere cazar.
En local manda la velocidad; en integración continua, la detección. **[n=1]**

### 7.3 Ramas: trabajar y desplegar no son lo mismo

El trabajo va a una rama de desarrollo; la rama principal **es la que despliega**. Integración
continua y firma corren en las dos; el despliegue, solo en la principal.

Se aprendió de la peor manera: un commit que solo tocaba un guion de publicación desplegó producción
entera, con su reinicio y su aviso de vigilancia. **[n=1]** La regla que lo cierra es que **el
fichero de despliegue no lleva la rama de desarrollo en su disparador**. Si algún día aparece ahí,
la separación desaparece.

### 7.4 Los avisos que emite la forja también son una puerta

Las puertas de §7.1 miran el árbol: el código, los *locks*, el contrato. Pero una forja moderna
—GitHub, GitLab— emite además avisos **que no están en el árbol** y que ninguna puerta local puede
ver: alertas de vulnerabilidad sobre las dependencias, *pull requests* de actualización abiertas
por un robot, y revisiones de código automáticas.

Esos avisos tienen un problema que no tienen los tests: **no fallan**. Se acumulan en una pestaña,
y revisarlos depende de que alguien se acuerde. En este proyecto la frase que lo describió fue
literal: «lo voy viendo y te voy diciendo, pero si se me pasa o se me olvida se queda por
revisar». Es la definición de un control que existe y no actúa, y la misma lección que §6: **se
cumple donde está mecanizado y se escapa donde sólo estaba escrito**. **[n=1]**

**Lo que hay que entender antes de mecanizarlo es dónde se calcula cada aviso**, porque de ahí sale
el diseño y no de la preferencia por bloquear pronto:

| Aviso | Contra qué se calcula | Dónde puede exigirse |
|---|---|---|
| Alertas de vulnerabilidad | La **rama por omisión** | Al mezclar a la principal, no antes |
| Revisión automática de código | La *pull request* | Antes de mezclar |
| *Pull requests* de actualización | Nada; simplemente existen | En ningún sitio: se informan |

La primera fila es la que sorprende. Como la alerta se calcula contra la rama por omisión, **un
arreglo que vive en la rama de desarrollo no la cierra**: seguirá abierta hasta que se mezcle. Una
puerta que bloqueara la *pull request* por «hay alertas abiertas» dejaría roja precisamente a la
que las corrige — y un punto muerto se resuelve siempre igual, desactivando la puerta. Por eso el
sitio de esa exigencia es **el despliegue**, que es el primer instante en que la foto es cierta.

**Y esa primera fila es también la que este proyecto construyó y acabó retirando, por una razón
que merece contarse.** Se escribió entera, con sus tests, y en su primera ejecución real respondió
un error de permisos: **el testigo automático de la integración continua no alcanzaba a leer las alertas**, y
no había permiso del flujo que lo arreglara. La alternativa era una credencial propia, de sólo
lectura y un solo permiso; se pidió, quedó pendiente de aprobación de la organización, y **se
decidió retirar el control en vez de insistir**. Dos razones, y las dos pesan más que el control:
no pedir una excepción a una política de credenciales que existe por algo, y conservar que el
repositorio **no tuviera ninguna credencial guardada** — desplegaba con federación de identidad, y
esa propiedad se pierde con el primer secreto y ya no se recupera.

Lo generalizable no es el detalle de la plataforma, es el orden de la decisión: **la frontera de
credenciales es parte del diseño de una puerta, no un trámite posterior**. Antes de construirla
conviene saber con qué permiso se va a leer la señal, y si conseguirlo exige una excepción, ésa es
una pregunta de gobernanza y no de ingeniería — con una respuesta legítima que es «entonces no hay
puerta». Aquí lo esencial no se perdió, porque las vulnerabilidades las sigue bloqueando la
auditoría de los *locks*, que no necesita credencial alguna; lo que se perdió es la reconciliación
con la pestaña, y decirlo en voz alta es la diferencia entre un hueco conocido y un hueco
disimulado. **[n=1]**

La tercera fila es la tentación contraria: bloquear por una actualización pendiente parece
riguroso y sólo enseña a saltarse la puerta. Una actualización que espera no es un defecto. Lo que
hace falta es que esté **a la vista en el mismo sitio y el mismo momento** en que se mira todo lo
demás.

**Y hay un detalle de temporización que decide si el control sirve o es decorativo.** La revisión
automática comenta **cuando termina**, que suele ser después de que la integración continua haya
pasado. Un control que sólo corriera con el *push* daría verde en el único instante en que todavía
no había nada que ver.

Lo natural sería que cada comentario y cada resolución volvieran a calcular el estado. **Este
proyecto lo intentó y las dos vías estaban cerradas**, y merece contarse porque el resultado
importa más que el detalle:

- No había ningún evento que la automatización admitiera **para la resolución de un comentario**.
  El que parecía obvio existe como aviso de la forja pero no como disparador, y ponerlo no dio un
  error de validación: dejó el control **sin arrancar**.
- Los eventos que **sí** existían llegaban retenidos a la espera de aprobación, porque quien los
  emite es el propio revisor automático y cuenta como agente externo. El ajuste que lo gobierna
  sólo era accesible con el repositorio ya público.

De ahí sale la regla, que es lo generalizable: **antes de construir una puerta sobre una señal
externa, comprueba que puedes reevaluarla después de actuar sobre ella.** Si puedes, es una
vigilancia. Si no puedes, es una **foto** — sigue valiendo, porque una foto a tiempo es mejor que
ninguna, pero entonces hay tres consecuencias que no son opcionales: se documenta como foto, el
mensaje de error dice cómo volver a calcularla, y **no se convierte en comprobación obligatoria**.
Una foto vieja que puede quedarse en rojo legítimamente acaba enseñando a usar la excepción de
administrador, y eso desactiva de paso todas las demás puertas. **[n=1]**

Tres reglas más, cada una contra un modo de degradarse:

- **Una sola lista de aceptaciones.** Un aviso que no se puede corregir —porque no hay versión
  corregida— se acepta por escrito, con motivo, firma y **caducidad**, en el mismo fichero que ya
  usa la puerta de dependencias (§7.1). Inventar una segunda lista para los avisos de la forja
  deja dos fuentes que se contradicen, y la que caduca es la que pierde.
- **Resolver el hilo es el acto que cuenta.** Un comentario de revisión automática puede ser
  cierto o falso —en este proyecto los ha habido de los dos—, así que lo que se exige no es
  obedecerlo sino **decidir sobre él**. Cerrar el hilo es lo que separa «lo he leído y decido que
  no» de «no lo he visto», y es lo único de las dos cosas que se puede comprobar.
- **«No pude mirar» no es «no hay nada».** Si la interfaz de la forja responde con un error de
  permisos, una llamada sin comprobar deja la lista vacía y el control informa de cero avisos
  **en verde**. Es exactamente la trampa de §6.3, y aquí es más fácil de cometer porque el error
  llega de fuera. La comprobación del error tiene que poner el paso en rojo, no escribir una
  advertencia en el registro.

  Esta regla **no es hipotética, y es la que pagó el viaje**: fue precisamente esa comprobación la
  que descubrió que el testigo automático no alcanzaba a leer las alertas. Sin ella, el control
  habría informado de cero alertas en verde de forma indefinida, dando **tranquilidad falsa sobre
  vulnerabilidades**, que es la peor clase de verde que puede tener un proyecto. El control acabó
  retirándose, pero el modo en que se descubrió que no servía es el único motivo por el que se
  supo a tiempo.

**Lo generalizable**: donde una herramienta externa emite avisos que nadie está obligado a mirar,
el marco exige una puerta que los mire por ti, colocada en el momento en que el dato ya es cierto,
y una lista escrita —con caducidad— para lo que se decide no arreglar. Y cuando esa puerta no se
puede construir —porque la señal no se puede leer, o leerla exigiría una excepción que no procede
pedir—, la respuesta del marco no es una puerta aparente: es **retirarla y anotar el hueco**. Un
control que no puede mirar es peor que ninguno, porque el hueco deja de verse.

---

## 8. Apertura del repositorio

### 8.1 Licencia

Este proyecto usa **AGPL-3.0-or-later**. Lo que hay que replicar es el razonamiento, no la
elección:

- Es software para **administraciones públicas**, financiado con dinero público. Que las mejoras
  vuelvan a la comunidad es coherente con su origen.
- La AGPL cubre el **§13**: quien ofrezca el software como servicio en red tiene que ofrecer la
  fuente a sus usuarios. Con GPL a secas, un despliegue como servicio por parte de un tercero no
  obliga a nada.
- Titularidad institucional, autoría personal. Se distinguen.

**Para otro proyecto la elección puede ser otra.** Lo que el marco pide es que esté **razonada por
escrito**, no que sea AGPL.

### 8.2 Certificado de origen (DCO)

Cada commit lleva `Signed-off-by`, con `git commit -s`. Certifica que quien commitea tiene derecho
a aportar ese código bajo la licencia del proyecto. Lo comprueba un *workflow*.

**Se exige también al mantenedor**, y no es simetría decorativa: un mantenedor que se exceptúa de
su propia política la deja sin fuerza.

### 8.3 Issues y la vía para proponer

Dos plantillas, y la segunda es la que importa en un proyecto multiorganización:

**Fallo.** Qué pasó, qué se esperaba, cómo reproducirlo, y **en qué modo de despliegue y con qué
configuración**: el mismo código se comporta distinto según cómo esté configurado.

**Propuesta.** Con una pregunta central que decide todo:

```markdown
## Qué falta

## Por qué lo necesita **cualquier** organización
<!-- La pregunta que decide si esto es material del principal o de tu fork.
     Si otra administración diría «me da igual», es material de fork. Si diría «lo necesito
     pero al revés», entonces lo que se propone no es la funcionalidad sino la OPCIÓN DE
     CONFIGURACIÓN que permite las dos. -->

## Cómo lo resuelves hoy
<!-- Si tienes un apaño en tu fork, cuéntalo: suele ser la mitad del diseño. -->

## Lo que NO debería hacer
<!-- Los límites de una propuesta se olvidan antes que su objetivo. -->
```

**Se propone antes de escribir código.** Contestar esa pregunta primero ahorra escribir lo que no
puede entrar.

La plantilla de *pull request* empieza por la misma pregunta: **¿por qué esto es generalizable?**

### 8.4 Un principal y tantos *forks* como organizaciones

El repositorio principal decide la dirección. Cada organización que despliega trabaja sobre **su
fork**, y lo generalizable sube por *pull request*. **La regla vale también para la institución
donde nació el proyecto**: su desarrollo entra como aportación, no como dirección.

Sin esa regla, en poco tiempo el principal *sería* el sistema de una institución concreta, y el
resto heredaría decisiones tomadas para un contexto que no es el suyo.

### 8.5 Lo que la documentación no resuelve

Una advertencia práctica. **[n=1]** Para abrir un repositorio, la documentación resuelve «qué no
puedo romper». No resuelve **«qué tarea cojo»**. Eso son *issues*, y sin ellos quien llega no tiene
por dónde entrar. Este proyecto llegó a tener toda la documentación escrita y **cero issues**, que
es la mitad del trabajo sin hacer.

---

## 9. Los errores que ya pagamos

Toda esta sección es **[n=1]** y toda es negativa. Es también la de más valor para otro equipo:
ninguno de estos errores es específico del proyecto. Son la forma en que fallan los agentes, los
tests y la documentación en cualquier equipo, y empezar sabiéndolo es la ventaja más barata que se
puede tener.

### 9.1 El medidor miente antes que el sistema

**Es el error más frecuente, con diferencia.** Ante una cifra extraña (un cero, un cien por cien,
un valor exacto que se repite, una comparación que se invierte), el fallo está en el instrumento
más veces que en el sistema. Y es **más fácil de creer**, porque confirma que había algo que
arreglar.

Ha ocurrido más de quince veces en este proyecto. Algunos ejemplos: «0 de 12 fuentes» era leer un
campo que no existía; «1.000 exacto» era medir una cosa distinta de la que decide; y «cuatro fichas
sin texto» lo tenían, guardado bajo otra clave.

**La variante peligrosa: un test recién escrito que sale en rojo es tan sospechoso como una cifra
extraña.** Ahí el rojo se interpreta como «falta implementarlo», y la prisa por arreglar tapa la
revisión del instrumento.

### 9.2 El doble de test se queda corto respecto al código

Un doble que enumera a mano lo que un módulo exporta se queda viejo en el siguiente cambio, y el
rojo aparece **lejos de su causa**: 19 tests fallando que parecían del menú de la aplicación, y eran
del doble.

Regla: **un solo doble por módulo, en un solo sitio.** Si un fichero de tests nuevo necesita el
mismo doble, los tests van al fichero que ya lo tiene.

### 9.3 Una guarda defensiva esconde un bug

Donde un `except` evita que un fallo tumbe el servicio, hace falta **un test del camino bueno**.
Este proyecto tuvo un arreglo inerte durante días porque un `except` se tragaba el error que
demostraba que no funcionaba.

### 9.4 Los dobles sin especificación esconden cambios de API externa

Un doble sin `spec=` acepta cualquier método, incluido uno que el SDK real renombró. Se descubre en
producción.

### 9.5 La duplicación se cuela en el documento que la prohíbe

El fichero de reglas enuncia «una sola fuente de verdad por cosa» y acabó duplicando buena parte
del documento de metodología. No fue descuido: cada vez que una regla necesitaba una frase más de
contexto, se escribía ahí en vez de en el documento largo, y la duplicación se acumula una frase a
la vez.

**El síntoma que lo delata no es el tamaño.** Es tener que editar la misma lista en dos sitios al
añadir una regla, y ver que la segunda copia casi se queda sin actualizar. Y hay una consecuencia
incómoda: al eliminar la duplicación puede ponerse rojo un guardarraíl **que estaba casando con la
copia** y no con el original. Un guardarraíl también puede estar vigilando la redundancia.

### 9.6 Un documento con estado incrustado envejece

El documento de «leer primero» de este proyecto llevaba una sección de estado fechada, y tres
bloques después mentía. **El estado va en un solo sitio** —las *issues* y los hitos; al principio,
el cursor—, y los demás documentos apuntan a él. Es P4 aplicado a lo que más tienta romperlo.

### 9.7 El mismo problema muerde tres veces

Un defecto de frontera con un proveedor externo mordió **tres veces en sitios distintos** antes de
que se arreglara como **clase** en vez de como caso. La segunda vez ya existía un módulo escrito
para evitarlo, y no se usó en los ocho sitios que lo necesitaban.

Regla: **a la segunda vez, guardarraíl.** No a la tercera.

### 9.8 La configuración inválida no se rechaza: se ignora

Un test que falla dice qué pasa y dónde. Una **configuración** que la plataforma no entiende no
suele hacer eso: la acepta y no hace nada, o crea una ejecución vacía que parece un fallo de otra
cosa. No hay línea que señalar, y lo que se ve es ausencia — que es lo más difícil de notar.

Ha pasado dos veces aquí, y en las dos el fichero se veía perfectamente bien:

- Los **nombres de ecosistema** del robot de dependencias. Un nombre que la plataforma no reconoce
  deja esa entrada sin efecto y **no avisa**: la única forma de saberlo es abrir el panel después
  del primer envío y mirar si el robot hizo algo.
- Un **disparador inexistente** en un flujo de automatización. Existía como aviso de la forja pero
  no como disparador. En lugar de rechazar el fichero, la plataforma dejó el flujo sin arrancar:
  una ejecución **sin ningún paso**, marcada como fallo, repetida en cada envío. El síntoma no
  apuntaba a la causa.

Lo que las dos comparten es que **un test local sí puede comprobarlas**, y por el mismo método:
la lista de valores admitidos se escribe en el guardarraíl, con la fecha en que se copió de la
documentación, y el test compara contra ella. No es elegante —hay que revisarla si la plataforma
añade valores—, pero convierte un fallo silencioso en un rojo con el nombre delante, y el modo de
fallo del propio guardarraíl es benigno: un falso rojo que se arregla añadiendo una línea.

Regla: **si un fichero de configuración lo interpreta un tercero, el conjunto de valores válidos
es parte del proyecto.** Escribirlo cuesta diez minutos; averiguarlo por ausencia costó un commit
las dos veces.

---

## 10. Comparación con otros marcos

| Dimensión | Marcos *spec-driven* (Spec Kit, Kiro) | Marcos de personas ágiles (BMAD) | Este marco |
|---|---|---|---|
| Origen | Herramienta con opinión, 2025 | Comunidad, 2025 | Ensayo y error en un proyecto real |
| Madurez | Meses. Ninguno se ha impuesto | Meses | **[n=1]** |
| Especificación | Fichero por *feature* | Documentos por rol | Prompts TDD + especificación por capacidad |
| TDD | No lo impone | No lo impone | **Obligatorio** |
| Trazabilidad del *por qué* | — | — | **Historial + ADR** |
| Documentación comprobada | — | — | **Guardarraíles** |
| Modelo de permisos | Delegado a la herramienta | — | **Explícito y con tests** |
| Autonomía | Alta, con confirmación por fase | Alta | **Media: bloque autónomo, decisiones humanas** |

**Qué tomar de ellos**: la granularidad de un fichero por unidad de trabajo, y el vocabulario
(*constitution*, *spec*, *plan*, *tasks*), que empieza a ser común y facilita que alguien de fuera
entienda el repositorio.

**Qué no tomar**: la promesa de autonomía por fases sin puerta de tests. Es donde DORA avisa: sin
estabilidad, la velocidad es caos acelerado. **[Evidencia]**

**Y qué no hacer**: adoptar una herramienta de orquestación para obtener lo que ya se tiene. Si un
equipo ya tiene plan, seguimiento del estado e historial funcionando, migrarlos al formato de un
marco cuesta la reescritura entera y devuelve lo mismo.

---

## 11. Cómo desplegarlo en un proyecto nuevo

### 11.1 El orden importa

Los siete documentos no se montan el primer día. Este orden evita escribir documentos que luego hay
que tirar:

| # | Paso | Por qué aquí |
|---|---|---|
| 1 | **Permisos y guarda, con sus tests** | Antes de que el agente ejecute nada |
| 2 | **`AGENTS.md` mínimo**: reglas duras, comandos del proyecto, prohibiciones | Es lo que el agente lee antes de escribir |
| 3 | **Integración continua con lint, tests y *lock* verificado** | Sin esto, TDD es una intención |
| 4 | **El primer bloque**, como un hito con sus *issues*, y cada *issue* escrita como un prompt TDD | Un bloque pequeño, para calibrar el método. Ver abajo por qué el contenido de prompt importa al empezar |
| 5 | **Historial** | En cuanto haya dos bloques |
| 6 | **Registro de decisiones** | A la primera alternativa descartada |
| 7 | **Especificaciones** | Cuando haya capacidades que garanticen algo |
| 8 | **Guardarraíles** | La primera vez que un documento se queda viejo |
| 9 | **Licencia, DCO, plantillas de issue** | Antes de abrir el repositorio, no después |

**Las especificaciones van en el paso 7 y no en el 1.** Escribir garantías antes de tener nada
que garantizar produce un documento que hay que reescribir entero al segundo bloque. Primero se
construye; cuando algo garantiza algo, se escribe.

**El estado va en *issues* desde el principio, pero el contenido del paso 4 es el de un prompt**
(§4.7). Son dos cosas distintas. Dónde se sigue el estado no admite discusión: con *issues* lo
sigue cualquiera, y un cursor sólo funciona mientras trabaja una persona (§4.4). Lo que importa al
empezar es **qué se escribe dentro**: un prompt con sus tests enumerados **obliga a decidir por
adelantado qué tiene que ser cierto**, y esa es la decisión que no se puede delegar en el agente.
Una *issue* que se queda en «arregla esto» produce tests que confirman lo que el código ya hace.
Así que, al principio, cada *issue* lleva en su cuerpo el prompt entero.

El cambio llega solo, y con señal: cuando la pregunta deja de ser «¿qué falta construir?» y pasa a
ser «¿qué ha aparecido que arreglar?», escribir los tests de cada *issue* por adelantado estorba,
y basta con una *issue* bien escrita. Ahí se afloja — y se comprueba que ninguna salvaguarda se
quedó por el camino.

### 11.2 El prompt de arranque

Es literal: se le da a un agente que tenga este documento accesible, y produce el andamio.

```markdown
Lee `MARCO_DESARROLLO_AGENTICO.md` y monta los documentos de gobierno de este proyecto.

CONTEXTO QUE TE DOY YO:
- Proyecto: <nombre y en una frase qué hace>
- Lenguajes y stack: <...>
- Cómo se ejecutan los tests: <comando exacto>
- Cómo se arranca en local: <comando exacto>
- Sistema operativo y shell de trabajo: <...>
- Directorio de trabajo permitido: <ruta absoluta>
- Licencia elegida y por qué: <...>
- Lo primero que hay que construir: <...>

QUÉ QUIERO QUE HAGAS, EN ESTE ORDEN, PARANDO DONDE SE INDICA:

1. Configuración de permisos según §3, adaptada a mi stack: los tres cubos y el hook de la
   guarda con las tres familias de riesgo (SO, borrado fuera de raíz, pérdida irreversible).
   Escribe también los tests de la guarda. **PARA y enséñame la tabla de permisos antes de
   seguir**: es la única parte que no puedo revisar después.

2. `AGENTS.md` según §4.1. Reglas duras, accionables, con los comandos exactos de mi stack.
   **Máximo 300 líneas** — la evidencia dice que la longitud moderada funciona mejor. Si algo
   necesita más razonamiento, va a un documento aparte enlazado. Si mi herramienta busca otro
   nombre, crea ese fichero con tres líneas que importen este.

3. Integración continua según §7.1, con las puertas que apliquen a mi stack. Lint antes de
   tests. Lock verificado.

4. El primer bloque según §4.3, para «lo primero que hay que construir»: un hito con entre 3
   y 7 issues, cada una con el prompt en su cuerpo, sus tests ENUMERADOS y su verificación de
   cierre con evidencia concreta. Si no tengo forja, escríbelo en un fichero por bloque con un
   cursor, y dime que habrá que migrarlo cuando haya una segunda persona.
   **PARA y enséñame el bloque antes de ejecutar nada.**

5. El historial vacío, con su cabecera explicando qué va en él.

6. Plantillas: registro de decisiones, issue de fallo, issue de propuesta (con la pregunta de
   §8.3), plantilla de pull request, y el fichero de la licencia elegida.

7. Un `CONTRIBUTING.md` con el ciclo de §5 y qué NO se le pide a quien contribuye desde fuera.

QUÉ NO HAGAS:
- No escribas especificaciones todavía (§11.1, paso 7): no hay nada que garantizar.
- No escribas guardarraíles todavía: llegan cuando un documento se queda viejo.
- No inventes cifras, umbrales ni métricas. Si algo hay que medir, deja escrito cómo se mide.
- No copies las decisiones de arquitectura del proyecto de origen: son de su dominio. Copia la
  FORMA.
```

### 11.3 Qué no copiar de este proyecto

Tres cosas de este marco pertenecen a su contexto de origen, y copiarlas sería un error:

1. **Las decisiones de arquitectura.** La separación entre nube y nodo local, la multitenencia por
   organización o la retirada de un conversor de documentos responden a un dominio concreto.
2. **La longitud del `AGENTS.md`.** El del proyecto de origen es más largo de lo que la
   evidencia recomienda. Empieza corto y deja que el guardarraíl lo mantenga así (§4.1).
3. **La AGPL.** La elección de licencia tiene que estar razonada para **cada** proyecto (§8.1).

### 11.4 Cómo saber si está funcionando

Sin métricas, esto es fe. Cuatro señales, y las dos primeras son las que de verdad importan.
**[n=1]**

| Señal | Qué indica |
|---|---|
| **Cuántas veces al mes un guardarraíl se pone rojo por un documento viejo** | Que la documentación se mantiene sola. Cero durante meses es sospechoso: probablemente pasa en vacío (§6.3) |
| **Cuántas veces el rojo era del instrumento y no del sistema** | Si baja, el método está calando. En este proyecto se anota cada vez |
| Tiempo desde que entra alguien nuevo hasta su primera *pull request* aceptada | Si la documentación sirve |
| Reversiones por bloque | Si el commit por paso está bien puesto |

**No se mide velocidad sin medir estabilidad.** Es la conclusión de DORA y la moraleja de METR a
la vez: quien mide solo velocidad concluirá que va más rápido, y se equivocará en 40 puntos.
**[Evidencia]**

### 11.5 Cómo vuelve lo aprendido al marco

Esta sección existe porque faltaba, y la señaló la primera revisión externa (equipo Teclab de la
UADTI, 2026-09-10): un marco que se copia de proyecto en proyecto **diverge**, y sin un camino de
vuelta las divergencias se quedan encerradas donde nacieron. Es exactamente lo que ya había
pasado allí entre dos proyectos.

**Las divergencias no son el problema: son los experimentos.** Copiar el marco y adaptarlo es lo
que debe ocurrir. Lo que falta no es evitarlo, sino un **criterio de promoción** y una
**cadencia**.

**El criterio sale de las etiquetas de evidencia que este documento ya usa.** Cada afirmación
lleva su estatus —`[n=1]` cuando viene de una sola experiencia, `[Evidencia]` cuando hay estudio
detrás, `[Convención]` cuando es práctica establecida—. De ahí la regla:

> Una práctica divergente entra en el marco común cuando **la han pagado dos proyectos
> distintos**. Con uno se anota como `[n=1]` diciendo dónde ocurrió; con dos deja de llevar la
> etiqueta y pasa a regla.

Así el marco crece con evidencia y no con opiniones, y se ve de un vistazo qué partes no han sido
probadas todavía fuera de su proyecto de origen.

**La propagación necesita dos cosas mínimas**, y ninguna es una herramienta:

1. **Una versión del marco declarada** en el `AGENTS.md` de cada proyecto. Sin número no hay
   contra qué comparar, y por eso hoy nadie compara.
2. **Una revisión periódica** en la que cada proyecto reporta sus divergencias. El diff lo hace
   el propio agente: «compara nuestras reglas con el marco vX y dime qué hemos cambiado y por
   qué». Son cinco minutos, y sin el número de versión son imposibles.

---

## 12. Bibliografía

**Evidencia empírica**

- METR, *Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity*
  (julio 2025) — el ensayo controlado de los 16 desarrolladores y las 246 tareas.
  <https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/>
- DORA / Google Cloud, *State of AI-assisted Software Development 2025* — la IA como amplificador.
  <https://dora.dev/dora-report-2025/>
- Anthropic, *2026 Agentic Coding Trends Report* — el reparto 70 % planificación / 20 % ejecución.
  <https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf>
- *Agent READMEs: An Empirical Study of Context Files for Agentic Coding*, arXiv:2511.12884 — la
  longitud moderada y las instrucciones explícitas. <https://arxiv.org/abs/2511.12884>
- *Graduated Human Oversight for Agentic Code Generation*, arXiv:2606.22484 — supervisión escalada
  por riesgo, matrices de permisos. <https://arxiv.org/abs/2606.22484>
- *Instruction Adherence in Coding Agent Configuration Files*, arXiv:2605.10039.
  <https://arxiv.org/abs/2605.10039>
- *Harness Engineering for Agentic AI Coding Tools: An Exploratory Study*, arXiv:2602.14690.
  <https://arxiv.org/abs/2602.14690>

**Estándares y convenciones**

- Especificación `AGENTS.md` — formalizada en agosto de 2025; donada a la *Agentic AI Foundation*
  de la Linux Foundation en diciembre de 2025. <https://agents.md>
- GitHub, *Spec-driven development with AI* y el repositorio `github/spec-kit`.
  <https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/>
  · <https://github.com/github/spec-kit>
- Michael Nygard, *Documenting Architecture Decisions* (2011) — el formato ADR.
  <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>
- *Developer Certificate of Origin* 1.1. <https://developercertificate.org/>
- Free Software Foundation, *GNU AGPL v3*. <https://www.gnu.org/licenses/agpl-3.0.html>

**Taxonomías de autonomía**

- Cloud Security Alliance, *Autonomy Levels for Agentic AI* (enero 2026) — seis niveles con
  controles por riesgo. <https://cloudsecurityalliance.org/blog/2026/01/28/levels-of-autonomy>
- Swarmia, *Five levels of AI coding agent autonomy, and why higher isn't always better*.
  <https://www.swarmia.com/blog/five-levels-ai-agent-autonomy/>

---

## Apéndice — El marco en una página

```
PRINCIPIOS          P1 supervisado, no autónomo   P2 medir, no sentir
                    P3 determinista antes que modelo   P4 una fuente por cosa
                    P5 el por qué se escribe   P6 lo mantenible se pone rojo

PERMISOS            permitir: leer, escribir, git, tests, paquetes, contenedores
                    preguntar: SO · borrado fuera de raíz · pérdida irreversible
                    denegar: lo que no tiene caso legítimo nunca
                    + guarda con tests propios

DOCUMENTOS          reglas · especificaciones · plan · estado (issues e hitos)
                    historial · decisiones · contribución

CICLO               bloque = unidad de interacción
                    RED → GREEN → REFACTOR → cierre → commit firmado por paso
                    4 causas para interrumpir, y una lista de cuándo NO
                    tests escalonados · verificación en navegador · informe de cierre

CONTROL             guardarraíles (documentación con test)
                    integración continua con puertas · sin paralelismo en CI
                    rama de trabajo ≠ rama que despliega

APERTURA            licencia razonada · DCO también al mantenedor
                    issue de propuesta con «¿por qué cualquier organización?»
                    principal + forks, sin fork privilegiado
```
