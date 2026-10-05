# El catálogo de funciones

Una **función** es código determinista con su contrato declarado, versionado, y compartido dentro
de la plataforma. Sirve para que una extracción de datos —contar las filas de un fichero de
gastos, leer los importes de un PDF de facturas, calcular un indicador— se escriba **una vez** y
la usen todas las plantillas de informe que la necesiten.

Antes del bloque FUN, el código aprobado de un script se **copiaba incrustado** en el bloque de
cada plantilla. Dos plantillas que necesitaran la misma extracción eran dos propuestas, dos
aprobaciones y dos copias; y un error en un script usado por N plantillas se arreglaba N veces. El
catálogo existe para que eso no vuelva a pasar: la plantilla **referencia** `función@versión`.

**Dónde está.** Desde el 2026-10-05 el catálogo tiene módulo y menú propios, **Automatización**
(módulo `automatizacion`, `/automatizacion/funciones`), y ya no cuelga de Informes: una función
externa no produce ningún informe. Lo que sigue en Informes son los scripts que quien redacta
propone para su plantilla (§6), porque son parte de redactar. El código del servidor sigue en
`modules/redaccion/`.

Este documento está escrito para tres lectores distintos, y cada sección dice para quién es.

---

## 1. Qué es una función, campo a campo

Una función tiene dos partes: la **función** (identidad estable) y sus **versiones** (el código y
el contrato concretos, inmutables una vez registradas).

### La función

| Campo | Qué es |
|---|---|
| `nombre` | Cómo se llama. Es lo que se ve en el catálogo. |
| `descripcion` | Para qué sirve, en una línea. |
| `organizacion_id` | La organización autora. **Nulo significa «de la plataforma»**. |
| `origen` | `autoservicio` (el código vive en el catálogo y corre en el sandbox), `paquete` (vive en el repositorio de un equipo y corre en el proceso) o `externa` (AUT.3: vive donde su autora lo tenga y **la plataforma no lo ejecuta**). |
| `entry_point` | Solo en `paquete`: `distribución:nombre`. |
| `publicada_en` | Cuándo se promovió a nivel de plataforma. Nulo si no lo está. |
| `valoracion_promocion` | La valoración escrita de quien la promovió. |
| `nivel` | **Derivado, no guardado.** 2 si es de una organización y sin publicar; 3 si está publicada, es de paquete o no tiene organización. |

`nivel` es derivado a propósito: una columna sería un tercer sitio donde vive el mismo hecho y
podría discrepar de los otros dos — el defecto que MT.4 le quitó a `is_global`.

### El origen `externa`, y lo que la plataforma no puede hacer (AUT.3)

Una organización que trabaja con cuadernos escritos por agentes de código tiene un problema de
**registro, no de ejecución**: no sabe cuáles circulan, quién los usa ni de qué versión. Las
normas de desarrollo ciudadano exigen registrar antes de compartir y prohíben la distribución
informal. `externa` es el sitio donde ese cuaderno se registra.

Tres cosas que este origen hace distintas, y las tres a propósito:

1. **No se ejecuta aquí.** `POST /funciones/{id}/run` responde **409** —no 423— con el motivo y
   con dónde sí corre. Un 423 diría «espera o cambia de versión»; aquí no hay nada que esperar.
   Registrarlo sin ejecutarlo es además lo que respeta la soberanía local: el código sigue
   corriendo donde corría, con las credenciales de quien lo usa.
2. **La auditoría es informativa.** Sus hallazgos se guardan y llegan a la cola de revisión, y
   **no bloquean el registro**: un programa que corre fuera usa red y disco legítimamente, y
   exigirle las reglas del sandbox sería aprobación previa por la puerta de atrás. Cuando el
   fichero no se puede leer como Python, se anota que **no se pudo auditar** en vez de dejar la
   lista de hallazgos vacía, que se leería como «está limpio».
3. **Suspender es un aviso, no un cerrojo.** La plataforma puede marcarla, sacarla de las
   recomendaciones y dejar constancia; no puede impedir que alguien la ejecute fuera. Se dice
   aquí porque aparentar un control que no existe es peor que no tenerlo.

### La versión

| Campo | Qué es |
|---|---|
| `version` | El ordinal en el catálogo: 1, 2, 3… |
| `code` | El código Python, en `autoservicio`. El fichero entero —`.py` o `.ipynb`— en `externa`. **Nulo en `paquete`**: una copia divergiría del `pip install`. |
| `code_sha256` | El hash del código (o de la fuente del `run` en un paquete). Es lo que permite decir meses después si lo que corrió era esto. |
| `version_paquete` | Solo en `paquete`: la versión semver instalada. |
| `entorno_ejecucion` | Solo en `externa`: **dónde corre**. Es el dato que distingue el origen, porque la plataforma no lo ejecuta; sin él el registro no dice de qué responde nadie ni con qué credenciales se toca el dato. Texto libre: es una declaración, no una taxonomía que se pueda comprobar desde aquí. |
| `contrato_entrada` | El `ContratoFuncion`: slots de fichero, parámetros y la declaración responsable. |
| `contrato_salida` | Siempre `ExtractionResult`. No se inventa un segundo esquema, porque dos esquemas divergen. Desde AUT.7 puede llevar **artefactos**: los ficheros que la función produjo. |
| `audit_result_json` | Lo que vio el auditor, **incluidos los avisos que no bloquearon**: es lo que la revisión posterior tiene que poder leer. |
| `estado` | `draft` · `registrada` · `suspendida` · `retirada` · `no_instalada`. |
| `autoria` | `ia` o `persona`. **No es una puerta**: nada se ramifica por este campo. Consta porque la revisión posterior quiere verlo. |

### La declaración responsable (forma parte del contrato)

| Campo | Qué es |
|---|---|
| `finalidad` | Para qué sirve la función. **Obligatoria**: sin ella el contrato ni se construye. |
| `categorias_datos` | Qué clases de datos trata. Vocabulario **abierto**, y **el mismo que el registro de actividad de REG**: con dos vocabularios, el catálogo y el registro no se cruzarían en una auditoría. |
| `declarada_por` | Quién declara. Una declaración responsable sin responsable no es una declaración. |
| `declarada_en` | Cuándo. |

El código `sin_declarar` existe en el vocabulario, y significa exactamente eso. Las funciones que
la migración de FUN.3 sacó de plantillas vivas lo llevan: no se inventó una categoría por ellas.

---

## 2. El ciclo de una versión

```
draft ──► registrada ──► suspendida ──► registrada
                    └──► retirada          (terminal)
                    └──► no_instalada      (solo paquete; lo decide `pip`)
```

**Registrar es compartir, y es automático.** Para que una versión quede `registrada` hacen falta
tres cosas, y ninguna es que una persona dé el visto bueno:

1. la **declaración responsable** completa,
2. la **auditoría** sin hallazgos críticos,
3. la **prueba en sandbox** superada.

Con eso, la versión es usable de inmediato. La revisión humana viene **después** (§4).

**Una versión registrada es inmutable.** Corregir es publicar otra. Sin esto, «arreglar una vez»
sería «cambiar en silencio informes ya aprobados». Los únicos campos que una versión registrada
admite son los de otra persona y otro momento: los de la revisión y los de la suspensión.

**El anclaje es exacto en autoservicio.** Una plantilla anclada a `función@1` ejecuta la versión 1
para siempre; publicar la 2 **no cambia ninguna plantilla**. Adoptar la 2 es una decisión de quien
mantiene la plantilla.

**En paquete el anclaje es por mayor**, que es lo que compra el semver: una plantilla anclada al
ordinal que trajo 1.2.0 sigue ejecutando cuando se instala 1.3.0, y un mayor distinto **falla en
alto** nombrando los dos. Lo que no se aproxima es el manifiesto: anota la versión instalada
**exacta** con su hash.

**Retirar es terminal.** `suspendida` vuelve; `retirada` no. Y una versión retirada o desinstalada
**no se borra**: hay manifiestos de informe que la citan por id, y un manifiesto que apunta a una
fila inexistente no se puede auditar.

**Un bloque anclado a algo que no se puede ejecutar falla en alto**, con el nombre de la función y,
si está suspendida, **el motivo**. Nunca queda vacío en silencio.

---

## 3. Quién puede qué

El servidor calcula `acciones_permitidas` y la pantalla **itera** esa lista; no decide. Si una
acción aparece, su endpoint no responde 403, porque la autorización se lee de la misma función que
llena el DTO.

| | Autora | Admin de la organización | Superadmin | Otra organización |
|---|---|---|---|---|
| Anclar una versión (`adoptar_version`) | sí | sí | sí | solo si está publicada |
| Publicar una versión nueva (`versionar`) | sí | sí | sí | no |
| Revisar (`revisar`) | **no** | sí | sí | no |
| Suspender (`suspender`) | **no** | sí | sí | no |
| Reactivar (`reactivar`) | **no** | sí | sí | no |
| Retirar (`retirar`) | sí | sí | sí | no |
| Solicitar la promoción | — | sí | — | no |
| Promover a plataforma | no | no | **sí** | no |

Dos reparticiones que no se mezclan:

* **Suspender es de quien revisa; retirar es de quien escribe.** La autora no puede reactivar lo
  que otra persona suspendió: si pudiera, suspender no sería una decisión, sería una sugerencia.
* **Revisar es de otra persona.** La autora de una función no aparece como revisora de su propia
  versión.

Y una función de **paquete** no ofrece `versionar` ni `promover`: se versiona con `pip` y ya es de
plataforma. Sí ofrece `retirar`, porque la plataforma tiene que poder vetar una instalada sin
esperar a que alguien la desinstale.

---

## 4. Correspondencia con la Instrucció 02/2026

Esta sección es para quien tenga que dar por bueno el diseño: la UADTI, la OIATI y el
Responsable institucional de IA. Está escrita contra el texto de la Instrucció, y cita por
sección para que se pueda contrastar.

### Los tres niveles

| Instrucció | En el catálogo |
|---|---|
| **Nivel 1** — uso personal (§5) | Fuera de la plataforma. Un script que alguien usa en su equipo no pasa por aquí, y no tiene que hacerlo. |
| **Nivel 2** — compartir dentro del servicio (§5, §8) | **Registrar una función en una organización.** Filtro automático (declaración + auditoría + sandbox), uso inmediato, **sin aprobación humana previa**, y revisión posterior. |
| **Nivel 3** — alcance superior al servicio (§5, §7) | **No tiene equivalente directo, y conviene no confundirlo.** En la Instrucció, cruzar la frontera del servicio significa **salir** del desarrollo ciudadano: pasa a desarrollo corporativo o al embudo de innovación. La «promoción a plataforma» del catálogo es una decisión interna de alcance, no ese tránsito. |

Esa tercera fila decía antes que el nivel 3 «es» la promoción o el origen paquete. No lo es: son
cosas distintas que se parecen, y tratarlas como la misma haría creer que promover una función
sustituye al circuito que la Instrucció prevé para lo que excede un servicio.

### Lo que el nivel 2 exige, y dónde está

* **§8.2, declaración responsable y registro**: es parte del contrato (`finalidad`,
  `categorias_datos`, `declarada_por`). Sin ella la versión no se registra, y el botón de
  guardar no se activa.
* **§8.2, filtro automático con puesta en uso inmediata**: auditoría AST sin hallazgos críticos
  + prueba en sandbox. Los avisos **no bloquean** —eso sería aprobación previa por la puerta de
  atrás— pero constan, y son lo que la revisión posterior lee.
* **§8.4, revisión posterior o por muestreo**: cola de revisión con **muestreo aleatorio**, y
  cuatro resultados posibles: `conforme`, `correcciones`, `reclasificada`, `suspendida`.
  **«Aprobada» no es uno de ellos, y no lo es a propósito**: en el nivel 2 no hay nada que
  aprobar.
* **La prohibición de la aprobación previa como condición para compartir** se hace cierta con un
  test que pide la misma versión a las dos superficies: aparece en la cola como `sin_revisar`
  **y** el resolutor la ejecuta, a la vez.
* **Regla 3, traza en la compartición**: no hay forma de compartir una función sin registrarla.
* **Regla 1, ecosistema autorizado**: los 17 módulos permitidos y las 63 capacidades denegadas de
  §5, servidos por API además de documentados. **Ratificados por la institución el 2026-09-29**
  (issue #122), junto con la ampliación de librerías —`python-docx`, `pymupdf`— que AUT.9 ya
  aplicó (§5).

  ~~**La red saliente hacia orígenes declarados NO entra.**~~ **Decidido el 2026-09-30 (issue
  #118): entra, con dos cerrojos.** Escribir hacia fuera no tiene sentido para una función de
  extracción; leer sí —bajar un PDF de una sede, el tomo de un presupuesto—, así que se abre
  **sólo por `GET`** y **sólo a los servidores que la declaración responsable enumera**.

  La razón por la que no entró con la ampliación de librerías sigue siendo buena: no es una
  librería, es una capacidad, y sostenía el argumento con el que se contestó la regla 2. Lo que
  pasó es que **se puede abrir sin tocar ese argumento**: quien baja el documento es la
  plataforma, no el guion, así que `requests` y `urllib` **siguen denegados** y la red del
  sandbox sigue cerrada. El detalle está en §4 y en `funciones_origenes.py`.

  Y `beautifulsoup4` **tampoco entró con esto**: parsear HTML es otra cosa que leer de la red, y
  nadie lo ha pedido todavía para una función.
* **§7, el nivel 2 no pasa por el embudo de innovación**: el circuito del catálogo es interno y
  no toca Teclab ni CEDIA. Estamos de acuerdo con el motivo que da la Instrucció — someter la
  extracción de una tabla de gastos al embudo reproduciría la burocracia que empuja al *Shadow
  IT*.

### Lo que la Instrucció exige: tres decisiones tomadas y una cosa de forma pendiente

Esto fue una lista de **huecos** frente a la norma —no de ideas, y por eso vivía aquí y no en un
apartado de mejoras—. **Los tres se cerraron el 2026-09-29** (issues #122 y #123), y se dejan
tachados en vez de borrados: quien vuelva a preguntarse por qué el plazo son 30 días o por qué no
hay una bandeja para la OIATI encuentra aquí la pregunta y la respuesta, que es más útil que
encontrar sólo la respuesta.

**La cuarta, que cierra la sección, sigue abierta** y no tiene fecha.

1. ~~**No hay plazo de revisión.**~~ **Cerrado el 2026-09-29 (issue #122): 30 días naturales.**
   §10 encarga fijar un compromiso de plazo máximo para la revisión posterior, «a fin de que el
   control no se convierta en un cuello de botella» — o sea que **el plazo no protege a la
   plataforma, protege a quien registra**. La cola marca `fuera_de_plazo` al superarlo y enseña
   cuál es el plazo, porque quien ve un incumplimiento sin saber contra qué no puede juzgar si
   la cola va mal o el número es corto.

   **Avisa y no bloquea**: vencer no retira la versión, no la suspende y no impide usarla.
   Bloquear al vencer sería aprobación previa con retardo, que es lo que el nivel 2 prohíbe.

   Cada despliegue lo cambia con `PLAZO_REVISION_POSTERIOR_DIAS`, sin tocar código. En la VM es
   una **variable del repositorio** con ese nombre, que `deploy.yml` lleva al contenedor; sin
   ella valen los 30 días, y el cambio entra en vigor con el siguiente despliegue. Sólo cuentan
   las versiones **sin revisar**: una revisada ya cumplió el plazo y no sale marcada.
2. ~~**No hay ruta automática a la OIATI.**~~ **Cerrado el 2026-09-29 (issue #123): no va a
   haberla, y es una decisión, no un hueco.** La revisión de la OIATI **se hace fuera de la
   plataforma**, a partir de la autodeclaración de categorías que la función ya lleva, o por
   petición previa de quien registra cuando tenga dudas.

   Lo que la plataforma aporta a esa revisión es el dato: cada versión declara sus categorías y
   la cola las enseña. Lo que **no** hace es encaminar, avisar ni esperar.

   **Y esperar era la opción que había que descartar explícitamente**: una función que no se
   pudiera usar hasta que la OIATI se pronunciara sería aprobación previa, que es justo lo que
   el nivel 2 prohíbe y lo que la decisión de la #121 acaba de ratificar.

   **El acceso de la OIATI**, si lo quiere, es el rol de administrador de la organización UJI.
   Conviene saber qué concede eso, porque es bastante más que leer la cola: configurar chatbots
   y prompts, listar a las personas de esa organización y **fijarles la contraseña**, emitir
   tokens de máquina y leer el registro de actividad. Es una decisión tomada con eso delante; se
   anota aquí para que no haya que redescubrirlo. (Desde la issue #94, fijar una contraseña deja
   marca y obliga a cambiarla en la primera entrada, así que ese uso no pasa desapercibido.)
3. ~~**Quién puede ordenar una suspensión no coincide.**~~ **Cerrado el 2026-09-29 (issue
   #123): se queda como está.** Suspender —y revisar— son del **administrador de la organización
   autora** o del **superadministrador**, que revisa las de todas. Nunca de quien escribió la
   función: revisar es de otra persona, y eso ya estaba y sigue.

   No coincide literalmente con §9, que lo asigna al Responsable institucional de IA, y la
   decisión es consciente: quien administra una organización es quien puede juzgar el impacto de
   detener sus informes, y el superadministrador cubre el nivel institucional.

   **Se sabe lo que cuesta**: una suspensión detiene informes —una plantilla anclada a esa
   versión falla en alto y dice por qué—, y en una función promovida a nivel de plataforma la
   puede ordenar la unidad autora aunque la estén usando otras. Queda dicho, no descubierto.

Y una cuarta, de forma: **§8.2 pide la declaración responsable acompañada de un «estudio de
integración simplificado» (Anexo I del Reglamento)**, y la declaración del catálogo son dos
campos. Puede que el estudio de integración de la propia plataforma cubra los casos que se
registran dentro de ella; puede que cada función necesite el suyo. Si lo necesita, los campos se
añaden al formulario.

### La diferencia honesta con la regla 2 de la Instrucció

**La regla 2 dice tres cosas**, y antes esta sección sólo citaba la primera:

1. la automatización se ejecuta **en el equipo de la persona** que la usa,
2. **con sus propias credenciales** y bajo su control,
3. **no suplanta identidades ni centraliza credenciales**;

y de ahí concluye que «la responsabilidad jurídica de lo que se introduce en los sistemas
corporativos sigue recayendo en la persona que ejecuta la solución».

**Dónde el catálogo no encaja**: la ejecución es central, no local. Eso es un hecho y no se
matiza.

**Dónde encaja mejor que el supuesto de la regla**: no hay credenciales que centralizar ni
identidad que suplantar, porque **una función no puede hablar con nada**. El auditor le prohíbe
`socket`, `requests`, `urllib`, `os`, `open` y `subprocess`, entre otras 63 capacidades, y la red
del sandbox está cerrada en producción. El riesgo que la regla 2 mitiga —lo que se *introduce* en
los sistemas corporativos— es estructuralmente imposible, no improbable.

**Y desde AUT.8 eso sigue siendo verdad, aunque una función ya pueda leer de fuera.** La decisión
del 2026-09-30 abrió la red saliente con dos cerrojos —sólo `GET`, sólo a orígenes declarados—,
pero **no le abrió la red al guion**: quien baja el documento es la plataforma, y el guion lo
recibe como un fichero de entrada más. La frase completa, que es la que hay que citar:

> Una función **no puede hablar con nada**. Lo que necesita de fuera lo pide la plataforma por
> ella, **sólo por `GET`** y **sólo a los servidores que su declaración responsable enumera**.

Tres razones por las que se hizo así y no dándole red al sandbox, porque la diferencia es toda la
garantía:

1. **La lista blanca se defiende fuera del proceso del guion.** Dentro, estaría escrita en Python
   corriendo junto al código del usuario, que es el peor sitio posible para un límite de
   seguridad.
2. **La red del sandbox sigue cerrada** (`internal: true`), así que un intento de salida no llega
   a ninguna parte en vez de llegar y ser rechazado.
3. **La comprobación del destino es la de I15**, que ya estaba escrita y probada, y que mira **en
   cada salto**: un origen declarado que redirige a una dirección privada no la burla.

**Por qué la lista blanca y no sólo el `GET`.** Un `GET` lleva datos en la URL:
`https://donde-sea.example/?nif=12345678Z` es una exfiltración completa y es una petición de
lectura. Lo que protege el dato no es el método, es el destino — y por eso los orígenes son parte
de la **declaración responsable** y no una opción de configuración.

**Y lo que no hace**: un guion no puede pedir una URL a mitad de ejecución. Bajar una página,
buscar enlaces dentro y bajar ésos son dos rondas.

**La pregunta, acotada así para que se pueda contestar**: ¿la regla 2 exige la ejecución local
**como fin**, o **como medio** para mantener la responsabilidad atribuible y las credenciales sin
centralizar? Si es un medio, el catálogo llega al mismo fin por otro camino, y en auditabilidad
por uno mejor: el código queda versionado con su hash, con declaración, con revisión y con rastro
de cada ejecución, cosas que no existen cuando el script vive en el portátil de alguien. Si es un
fin, hace falta una excepción escrita.

#### Contestada el 2026-09-29 (issue #121)

**La regla es un suelo, no un techo.** La institución que despliega ha decidido que la ejecución
local del nivel 2 significa que **no hay obligación** de ejecutar en la plataforma, y no que esté
prohibido hacerlo. Como ejecutar dentro da más control, es **preferible**. No hace falta ninguna
excepción escrita.

Cuatro consecuencias, y conviene leerlas juntas porque una sola se malinterpreta:

1. **Registrar en la plataforma vale como la declaración** que el nivel 2 exige. Esto ya era así
   por construcción —registrar una función *es* el acto de declararla, y sin declaración
   responsable no se registra—, así que la decisión ratifica el diseño en vez de cambiarlo.
2. **Es voluntaria.** Se animará a quien declare un desarrollo de nivel 2 a usarla, y no se le
   obligará. Por eso **las funciones de origen externo (AUT.3) no son un plan B**: son la otra
   mitad permanente del catálogo. Quien prefiera seguir ejecutando en su equipo registra ahí, y
   la institución sabe igualmente qué circula.
3. **La Instrucció no va a nombrar la plataforma**, porque es un desarrollo experimental y no
   está en producción a efectos institucionales. Así que **esta sección es nuestra lectura del
   texto, no algo que el texto prevea**, y conviene no leerla al revés: nada de lo que hay aquí
   puede citarse como «la Instrucció contempla la plataforma».
4. **Y la comparación de arriba sigue en pie tal cual.** No se ha matizado que la ejecución sea
   central: lo es. Lo que se ha decidido es que eso no incumple la regla.

### Y una pregunta anterior a todas: ¿esto es desarrollo ciudadano?

La matriz de decisión de **§4** reparte entre desarrollo corporativo y desarrollo ciudadano, y
**basta que un criterio caiga en la columna corporativa** para derivar el caso a la UADTI. Dos
caen:

* **Sensibilidad del dato.** La columna ciudadana dice «la solución no guarda datos fuera del
  equipo local». Los ficheros que procesa una función del catálogo viven en el almacenamiento de
  la plataforma.
* **Valor de la información generada.** La columna ciudadana dice «resultados de uso interno y
  acotado a la tarea del servicio», y el párrafo de cierre de §4 es explícito: cuando una
  automatización empieza a generar **indicadores de seguimiento o cuadros de mando**, deja de ser
  herramienta de productividad y debe derivarse a desarrollo corporativo. El módulo de informes
  es, literalmente, para informes de seguimiento.

**La lectura que proponemos**, y que nos parece la honesta: el catálogo **no es** una herramienta
de desarrollo ciudadano pidiendo el nivel 2. Es **un sistema corporativo** —mantenido, versionado,
auditado y desplegado por quien opera la plataforma— que aplica **dentro** la agilidad del nivel
2: declaración, uso inmediato y revisión posterior en lugar de aprobación previa.

Si esa lectura vale, la pregunta sobre la regla 2 casi desaparece: la regla 2 regula el desarrollo
ciudadano, y esto no lo es. Lo que quedaría por decidir es **qué control previo** quiere la UADTI
sobre un sistema corporativo que acepta código de sus usuarios, que es una conversación distinta
y más sencilla que una excepción a una regla.

**Nada de esto lo puede decidir la plataforma.** Hacía falta un «sí» explícito, no un silencio,
y **llegó el 2026-09-29**: la regla de ejecución local es un suelo y no un techo, así que usar la
plataforma es preferible y voluntario. Está contestado más arriba, en «Contestada el 2026-09-29».

---

## 5. La caja de herramientas del auditor

Para quien vaya a escribir o revisar una función de autoservicio. **Estas listas salen del
código** (`services/script_auditor.py`) y las sirve `GET /api/v1/verificaciones/codigo/reglas`; un
test comprueba que este documento no se desvía de ellas.

**Módulos permitidos** (17): `base64`, `collections`, `datetime`, `docx`, `fitz`, `io`, `json`,
`math`, `matplotlib`, `numpy`, `openpyxl`, `pandas`, `pdfplumber`, `re`, `seaborn`, `typing`,
`unicodedata`.

**La lista la fija la institución, no la plataforma.** Los dieciséis primeros se ratificaron el
2026-09-29 (issue #122) y en el mismo acto se aprobó la ampliación que AUT.9 aplicó: `docx` —
que se instala como `python-docx`— y la instalación real de `fitz` — que es `pymupdf` y llevaba
meses **permitido y sin instalar**, así que un guion que lo importara moría con
`ModuleNotFoundError` dentro del sandbox. Lo que **no** entró son `requests` y `beautifulsoup4`:
la red saliente no es una librería, es una capacidad. **Se abrió el 2026-09-30 (AUT.8, issue
#118) sin añadir ninguna librería**: el documento lo baja la plataforma y el guion lo recibe como
fichero de entrada, así que `requests` y `urllib` siguen denegados. Ver §4.

### Con qué nombre se instala cada una, y cuál arrastra copyleft

**El «para qué sirve» de cada módulo no se copia aquí: lo sirve la API**, en
`GET /api/v1/verificaciones/codigo/reglas` y en la herramienta MCP `reglas_de_auditoria`, con una
ficha por módulo. Es el mismo criterio que con las reglas del auditor — quien escribe el guion
**fuera** lee la API, no este documento, y una segunda copia en prosa divergiría en semanas.

Lo que sí va aquí son las dos cosas que son **decisiones** y no datos de uso:

| Módulo | Se instala como | Licencia |
|---|---|---|
| `pandas`, `numpy`, `seaborn` | `pandas`, `numpy`, `seaborn` | BSD-3-Clause |
| `openpyxl`, `pdfplumber` | `openpyxl`, `pdfplumber` | MIT |
| `docx` | `python-docx` | MIT |
| `fitz` | `pymupdf` | **AGPL-3.0** (o comercial de Artifex) |
| `matplotlib` | `matplotlib` | PSF-based |
| `base64`, `collections`, `datetime`, `io`, `json`, `math`, `re`, `typing`, `unicodedata` | — | Biblioteca estándar |

**Las dos librerías de PDF son complementarias y están las dos a propósito.** En la aplicación
anterior el módulo de extracción **leía con las dos y componía las dos lecturas** antes de
dárselas al modelo, precisamente para que tuviera más de donde agarrarse al escribir el guion; y
según cómo esté estructurado el documento, interesa una o la otra. **No son alternativas entre
las que haya que decidirse una vez**, y por eso ninguna de las dos sobra.

**`fitz` es la única con copyleft fuerte**, y conviene saberlo antes de escribir, no después. No
afecta a la plataforma —que ya es AGPL-3.0-or-later y ya distribuye GPL en el modelo de spaCy de
la anonimización—, pero **sí afecta al guion que escribas fuera**: si ese mismo código acaba
viviendo en un producto que no sea AGPL, la pregunta aparece allí. Si el documento se deja leer
con `pdfplumber`, esa pregunta no llega a plantearse.

**Capacidades denegadas** — las tres familias, y por qué cada una:

* **Salir de la máquina**: `socket`, `requests`, `httpx`, `urllib`, `http`, `ssl`. Un script de
  extracción no tiene por qué hablar con nadie, y si pudiera, podría llevarse los datos.
* **Tocar el sistema**: `os`, `sys`, `subprocess`, `shutil`, `open`, `chmod`, `remove`,
  `unlink`, `rmtree`, `popen`, `system`, `spawn`, `pty`, `tty`, `platform`, `threading`,
  `multiprocessing`, `concurrent`, `ctypes`, `cffi`.
* **Tocar la propia plataforma**: `fastapi`, `uvicorn`, `nicegui`. Un script de extracción que
  importara el servidor podría registrar rutas, leer la configuración o apagarlo — y estos tres
  están instalados en el mismo entorno, así que sin prohibirlos explícitamente el `import`
  funcionaría. (`nicegui` sigue en la lista aunque el cliente NiceGUI se retirara el 2026-09-04:
  prohibir algo que no está instalado no cuesta nada, y quitarlo sólo tendría sentido el día que
  se pueda asegurar que ningún despliegue lo tiene.)
* **Reescribirse a sí mismo**: `eval`, `exec`, `compile`, `__import__`, `importlib`, `builtins`,
  `getattr`, `setattr`, `delattr`, `globals`, `locals`, `vars`, `inspect`, `ast`, `code`,
  `codeop`, `dis`, `marshal`, `pickle`, `shelve`, `gc`, `types`, `traceback`, y los atributos de
  introspección (`__class__`, `__globals__`, `__code__`, `__bases__`, `__mro__`,
  `__subclasses__`, `__builtins__`, `__dict__`, `__closure__`, `__loader__`, `__module__`).
  Sin esta familia, la lista de módulos no serviría de nada: se saltaría en una línea.
* **Rutas absolutas**: un script que escribe en `C:\...` o `/var/...` funciona en el portátil de
  quien lo escribió y no en el despliegue, donde el almacenamiento es un servicio.

**Las seis reglas y su nivel**:

| Regla | Nivel |
|---|---|
| `syntax-error` | CRITICAL |
| `forbidden-call` | CRITICAL |
| `interpreter-access` | CRITICAL |
| `absolute-path` | CRITICAL |
| `forbidden-module` | CRITICAL |
| `module-not-whitelisted` | WARNING |

`module-not-whitelisted` es **WARNING** y no CRITICAL a propósito: un módulo desconocido no es
necesariamente peligroso —puede ser útil y faltar en la lista—, así que no bloquea el registro y
sí llega a la revisión posterior, que es quien puede decidir ampliar la lista.

> **Petición explícita a la UADTI**: estas reglas se escribieron desde el análisis del riesgo de
> un script de extracción, no desde la norma. Hay que contrastarlas con **el Anexo III.3 del
> Reglamento** —que es el que §8.4 de la Instrucció cita para el análisis estático— y con las
> **Guías Operativas Técnicas**, que según §10 detallarán el ecosistema autorizado y el
> procedimiento de revisión. Si alguna de las dos es más estricta en algo, manda la norma; si es
> más laxa, se queda lo estricto y se dice por qué.

---

## 6. Llevar tu script al catálogo

Para la persona referente de un servicio que ya tiene un script que funciona. **Esta sección va
por pantalla**: no hace falta escribir nada fuera del panel.

Tu script de nivel 1 ya hace lo que tiene que hacer. Lo que el catálogo te pide es **declararlo**,
y eso es lo que permite que otra persona lo use sin leerlo.

### Un ejemplo completo: un cuaderno real convertido

En [`docs/ejemplos/funciones/presupuesto/`](ejemplos/funciones/presupuesto/) está el cuaderno del
presupuesto propio convertido en **dos funciones encadenadas**, con sus contratos y un generador
de datos sintéticos (AUT.10, issue #120). Primero **anonimiza** y después hace el **CSV limpio y el
Word** sobre lo anonimizado. Lo que cuesta adaptar al pasar de un cuaderno a una función, y cómo se
resolvió allí:

- **Leer un fichero de texto sin `open`**, que el auditor deniega: con
  `pandas.read_csv(ruta, header=None, sep="\x1f", quoting=3)`, una fila por línea.
- **Lo que el cuaderno leía de tu Drive** —la prosa de un Google Doc— pasa a un fichero que se
  sube, aquí un Markdown con los mismos marcadores.
- **Sin `pip install`**: lo que la función importa tiene que estar en el ecosistema autorizado (§5).
- **El sandbox no usa la misma versión de pandas que el modo local**, así que un guion se prueba
  en los dos. Los dos tests del ejemplo lo hacen.

### El recorrido, paso a paso

Entra en **Informes → Pedir un script** (`/redaccion/scripts/wizard`). El asistente tiene siete
pasos y los cinco primeros ya existían; lo que cambia al final es que ahora declaras.

1. **Di qué necesitas, en tu idioma.** «Cuenta las filas del fichero mensual de gastos». El
   modelo propone el código y lo pasa por el auditor antes de enseñártelo (§5).
2. **Sube un fichero de prueba.** Es el tuyo, el de verdad.
3. **Anonimízalo si lleva datos personales.** El asistente te dice qué columnas ha detectado; si
   no hace falta, se puede omitir.
4. **Ejecútalo en el sandbox** con ese fichero y mira el resultado.
5. **Valida el resultado**: eres quien sabe si esa cifra es la correcta.
6. **Declara** (el paso nuevo, y el que convierte tu script en una función compartida):
   - **Para qué sirve** — una frase. Es lo que otra persona leerá en el catálogo para decidir si
     le vale, y lo que quien revise leerá para juzgar si el alcance es el que dices.
   - **Qué datos trata** — una o varias categorías. Salen del catálogo de tu organización, y si
     la que necesitas no está, la escribes: el vocabulario está para revisarse, no para
     encajarte.
   - **Cómo se llamará** en el catálogo (opcional; si lo dejas en blanco se pone un nombre por
     defecto).
7. **Guardar.** Y ya está: tu función queda **registrada y usable**.

El botón de guardar no se activa hasta que hay finalidad y al menos una categoría. No es un
formulario quisquilloso: **guardar es compartir**, y compartir sin declarar es exactamente lo que
la Instrucció no permite.

### Lo que pasa cuando pulsas guardar

Nadie tiene que aprobártelo. El auditor ya leyó tu código sin ejecutarlo y el sandbox ya lo
ejecutó con tus datos; con eso y tu declaración, la función entra en el catálogo como **v1
registrada** y cualquier plantilla de tu organización puede referenciarla desde ese momento.

Después aparecerá en **Automatización → Revisión posterior** (`/automatizacion/funciones/revision`),
y ahí otra persona puede pedirte correcciones,
reclasificar su alcance o suspenderla si encuentra un problema. Mientras eso no pase, funciona —
y si te la suspenden, el informe que la usaba falla diciendo el motivo, no en silencio.

### Si necesitas corregirla

No edites la v1: **publica una v2**. Vuelve al asistente, pide el arreglo y guarda indicando que
es una versión nueva de la misma función. Las plantillas ancladas a la v1 siguen ejecutando la v1
hasta que su responsable decida adoptar la v2 — así un arreglo tuyo no cambia por sorpresa un
informe que otra persona ya había revisado.

### El protocolo del script no cambia

Sigues asignando `result`, y sigues recibiendo `file_path`, `raw_text` y `options`. No se te pide
reescribir nada: cambiar el protocolo es lo que empuja a la gente a seguir trabajando por su
cuenta, y es justo lo que el catálogo existe para evitar.

Si la función pide **varios ficheros**, el primero sigue llegando como `file_path` y todos, el
primero incluido, están en `options["ficheros"]` por su slot, **cada uno con su ruta real**:

```python
presupuesto = pandas.read_csv(options["ficheros"]["presupuesto"])
clasificacion = pandas.read_csv(options["ficheros"]["clasificacion"])
```

Cada fichero conserva su nombre y su extensión (pandas elige el motor por ella), y va en su propia
carpeta, así que dos slots con ficheros que se llamen igual no se pisan. Juntos, los documentos de
entrada no pueden pasar de **64 MB**: el sandbox los guarda en un temporal de 128 MB que comparte
con los ficheros que la función produzca. Pasarse se dice antes de ejecutar, con las dos cifras.

### La misma cosa, en código

Si vas a integrar por API o a empaquetar una función (§7), el contrato que la pantalla rellena por
ti es éste:

```python
ContratoFuncion(
    # Los ficheros que pide, cada uno con su clase: excel, pdf, markdown o text.
    slots=[
        {"slot_id": "gastos", "kind": "excel", "required": True,
         "label": {"es": "Fichero de gastos", "ca": "Fitxer de despeses"}}
    ],
    # Los parámetros tipados. Un parámetro **es** un descriptor de campo de interfaz, así que el
    # formulario sale de aquí sin escribir nada en el frontend.
    parametros=[
        {"slot_id": "umbral", "field_type": "number", "label": {"es": "Umbral"},
         "required": False}
    ],
    # La declaración responsable, que en la pantalla son los dos campos del paso 6.
    finalidad="Contar las filas del fichero de gastos de un servicio",
    categorias_datos=["dades_pressupostaries"],
)
```

Las extensiones que acepta cada `kind` las manda el servidor en el descriptor, así que no hay que
repetirlas en ningún sitio.

---

## 7. Empaquetar una función

Para el primer equipo de desarrollo que mantenga funciones en su propio repositorio. El ejemplo
completo está en `server/tests/fixtures/paquete_funcion_demo/`.

### El descriptor

```python
from server.app.modules.redaccion.funciones_paquete import FuncionEmpaquetada

CONTAR_FILAS = FuncionEmpaquetada(
    nombre="contar_filas",
    version="1.2.0",          # semver de tres números, obligatorio
    contrato=CONTRATO,        # el mismo ContratoFuncion que una de autoservicio
    run=contar_filas,         # (EntradaValidada) -> ExtractionResult
)
```

El *entry point* apunta a una **instancia**, no a una factoría: así la plataforma puede validar tu
contrato antes de ejecutar una sola línea de tu paquete.

### El grupo

```toml
[project.entry-points."govgenai.funciones"]
contar_filas = "paquete_funcion_demo:CONTAR_FILAS"
```

El `entry_point` del catálogo es `distribución:nombre` — `paquete-funcion-demo:contar_filas`.

### Qué valida la plataforma al arrancar, y qué hace si falla

Descubre los *entry points*, valida cada contrato con **el mismo validador** que usa una función
de autoservicio, y **detiene el arranque** si algo no cuadra, nombrando paquete y función:

* contrato incoherente,
* versión que no es semver,
* `run` que no es invocable,
* dos *entry points* que declaran lo mismo,
* un *entry point* que no se puede importar.

Falla en alto y no «avisa y sigue» porque un servidor en pie al que le falta una función da el
síntoma mucho después, como «la plantilla referencia algo que no existe», sin ninguna pista del
paquete roto.

La sincronización es **idempotente**: arrancar dos veces no crea nada.

### La regla del mayor

Publicar **1.3.0** sobre plantillas ancladas a 1.2.0: se ejecuta 1.3.0, y el manifiesto anota
1.3.0. Publicar **2.0.0**: el bloque **falla en alto** nombrando el mayor anclado y el instalado,
porque tu contrato puede haber cambiado. Reanclar es una decisión de quien mantiene la plantilla,
después de revisar.

Desinstalar el paquete pasa todas sus versiones a `no_instalada`; la función **se conserva**.

### Qué registra el manifiesto

`funcion_id`, `nombre`, `version` (el ordinal del catálogo), `origen`, `code_sha256` y
`version_paquete` **exacta**. Es lo que permite responder «qué corrió» sobre un informe de hace
seis meses.

### La frontera de confianza, sin rodeos

**Tu `run` corre in-process, en el servidor, con los datos del cliente, y sin sandbox.** No hay
aislamiento. La confianza está en quien instala el paquete en el despliegue, exactamente como en
un plugin de pytest o de Airflow. Lo que la plataforma controla no es tu código: es quién puede
hacer `pip install`.

Lo que sí se valida siempre es **la entrada contra tu contrato antes de llamarte** y **la salida
como `ExtractionResult` después**. Por eso tu `run` no tiene que defenderse de un slot que falta.

### Una advertencia sobre la dependencia

Hoy los tres nombres que necesitas (`FuncionEmpaquetada`, `ContratoFuncion`, `ExtractionResult`)
viven en la plataforma, así que la necesitas como dependencia de desarrollo. Cuando aparezca un
segundo consumidor se moverán a un `govgenai-sdk` ligero, y no cambiará nada más: ni el grupo del
*entry point*, ni la forma del descriptor, ni el anclaje. Está dicho aquí para que no lo
descubras a mitad del primer intento.

---

## 7.bis. Producir ficheros, y no sólo cifras (AUT.7)

Hasta aquí la salida de una función eran **cifras**: tablas, métricas y texto para un bloque de
informe. Las tareas reales de una unidad no acaban así — acaban en un Excel que alguien manda, un
Word maquetado o un CSV limpio. Mientras la salida fueran sólo cifras, esas tareas se quedaban
fuera del catálogo, y fuera del catálogo es **sin declaración, sin auditoría, sin versionado y
sin registro**.

### Declararlo, que es lo primero

**Una función que no lo declara no puede producir ficheros**, y ése es el defecto. Se declara en
el contrato:

```python
ContratoFuncion(
    slots=[...],
    parametros=[...],
    finalidad="Sacar el CSV limpio del presupuesto",
    categorias_datos=["dades_pressupostaries"],
    artefactos=ArtefactosDeSalida(
        maximo=2,              # cuántos ficheros como máximo
        maximo_bytes=5_000_000,  # cuánto pueden pesar entre todos
        retencion_dias=7,      # cuánto se guardan; obligatorio, con techo de 30
    ),
)
```

Los topes **van en el contrato y no en una constante del servidor**: una función que saca un
Excel de 200 KB y otra que saca cincuenta PDF no pueden compartir un número inventado a medias
entre las dos. Y son además lo que la revisión posterior lee para saber qué se autorizó.

### Escribirlos

El guion recibe una variable más, `output_dir`, y escribe ahí:

```python
import pandas
df = pandas.read_csv(file_path)
df[df["importe"] > 0].to_csv(output_dir + "/limpio.csv", index=False)
result = {"metrics": [{"name": "filas", "value": len(df)}]}
```

Tres cosas que conviene saber antes de intentarlo de otra forma:

* **No hay manera de escribir a mano.** El auditor deniega `open`, así que un fichero se produce
  a través de una librería —`to_csv`, `to_excel`, `doc.save(...)`—. No es una incomodidad: es lo
  que mantiene acotado qué puede aparecer ahí.
* **Sin subdirectorios.** Sólo son artefactos los ficheros que quedan directamente en
  `output_dir`; el nombre de un artefacto no puede llevar ruta.
* **El directorio no sobrevive a la ejecución.** Ni para ti ni para nadie: si persistiera, la
  siguiente ejecución entregaría tus ficheros.

### Qué pasa si te pasas del tope

**Falla en alto y no recorta.** Entregar tres de los cinco ficheros que escribiste sería un
resultado parcial con aspecto de completo, y quien lo recibe no tiene cómo notarlo. El error dice
los dos números, el tuyo y el declarado.

Y si escribes ficheros **sin haberlos declarado**, se descartan y se te dice cuántos: descartar
en silencio te dejaría creyendo que tu Excel se entrega.

### Recogerlos

`POST /funciones/{id}/run` los devuelve **por referencia, no por contenido** — devolver el Excel
en base64 dentro del JSON haría que una respuesta de metadatos pesara megabytes:

```json
{
  "metrics": [{"name": "filas", "value": 128}],
  "artefactos": [
    {
      "id": "7f3a…",
      "nombre": "limpio.csv",
      "media_type": "text/csv",
      "bytes": 4096,
      "sha256": "9130c489…",
      "expira_en": "2026-10-07T09:12:00Z",
      "descarga": "/api/v1/funciones/artefactos/7f3a…"
    }
  ]
}
```

El `sha256` está para que compruebes lo que descargas. **Y `expira_en` está porque la referencia
caduca**: sin esa fecha, quien guarda el enlace descubre la retención el día que le devuelve un
404.

La descarga usa **el mismo scope que ejecutar**, `funciones:execute`. No hay uno aparte porque no
tendría sentido en ninguna de las dos direcciones: sin ejecutar no hay fichero, y ejecutar sin
poder recogerlo no sirve de nada.

### La retención

Pasado el plazo, **el fichero deja de servirse**: responde 404, igual que si no existiera o fuera
de otra organización — distinguirlos contaría que ese fichero existe en otra organización.

**Y se borra de verdad**, del almacenamiento y de la tabla, porque dejar de servirlo no libera el
sitio y el argumento de esto es de protección de datos. Lo hace un barrido que el arranque de la
aplicación lanza solo y que pasa **cada seis horas**: lo caducado se borra, como mucho, un cuarto
de día tarde. Hasta la PR #210 el barrido existía y no lo llamaba nada.

Si una ejecución falla después de subir sus ficheros —al guardar el registro, por ejemplo—, los
ficheros se borran en el acto: una subida no forma parte de la transacción, y un fichero sin
fila que lo nombre no lo encontraría nunca el barrido.

El tope de lo que una función puede declarar es **64 MB**: el sandbox guarda entrada y salida en
el mismo temporal de 128 MB, y la entrada ya puede ocupar la mitad.

Y esto **no es la política de retención de la plataforma**, que sigue sin existir. Es el tramo
estrecho que hacía falta para que `retencion_dias` no fuera una promesa sin nada detrás.

---

## 7.ter. Pedir documentos de fuera (AUT.8)

Una función puede necesitar un documento que no está en la plataforma: el tomo de un presupuesto
en la sede de la GVA, una resolución del BOE. Desde el 2026-09-30 puede pedirlo, con dos
cerrojos: **sólo lectura** y **sólo de los servidores que declare**.

### Declarar los servidores

Va en el contrato, y **forma parte de la declaración responsable**: enumerar de dónde se lee es
decir de dónde vienen los datos.

```python
ContratoFuncion(
    slots=[SlotDeFichero(slot_id="tomo", kind="pdf", required=True)],
    parametros=[],
    finalidad="Contar las subvenciones nominativas del tomo",
    categorias_datos=["sin_datos_personales"],
    origenes=["sede.gva.es", "www.boe.es"],
)
```

Tres cosas que un origen **no** puede ser, y las tres son formas conocidas de saltarse una lista
blanca:

| No vale | Por qué |
|---|---|
| Una URL (`https://sede.gva.es/docs`) | Habría que declarar cada documento, o aceptar prefijos — y un prefijo se burla con `https://sede.gva.es@atacante.example/`, que lleva el origen dentro y apunta a otro sitio |
| Un comodín (`*.gva.es`) | Lo hereda cualquiera que consiga un subdominio |
| Una dirección IP | No dice de quién es el servidor, y salta la comprobación del nombre |

Y la coincidencia es **exacta**: declarar `gva.es` no autoriza `otra.gva.es`. Si hace falta un
subdominio, se declara.

### Pedirlo

`POST /funciones/{id}/run` acepta `urls`, una por slot:

```json
{
  "version": 1,
  "urls": {"tomo": "https://sede.gva.es/documentos/tomo.pdf"}
}
```

Va aparte de `ficheros` a propósito: una referencia de almacenamiento es un documento que ya
tienes, y una URL es uno que le pides a la plataforma que traiga. Mezclarlas obligaría a adivinar
cuál es cuál por la forma de la cadena.

Una URL de un servidor no declarado responde **422 y no toca el sandbox**, igual que cuando la
entrada no cumple el contrato: una URL rechazada no puede haber gastado una ejecución. Si el
origen sí está declarado y el servidor remoto falla, es un **502** — el problema no es de tu
petición.

**Y lo que se puede rechazar sin red, se rechaza sin red**: un slot que el contrato no declara, o
`urls` para una función empaquetada, dan 422 **antes** de pedir nada fuera.

Lo que comprueba cada descarga:

- **Cada salto, no sólo el primero.** La lista blanca y la red pública se comprueban en la
  petición inicial **y en cada redirección**. Un origen declarado que redirige a otro servidor
  se para en ese salto, antes de hablar con él.
- **Hasta el tope, y no más.** Se lee a trozos y se deja de leer al pasarse: 50 MB por
  documento, y entre todos los de una ejecución, lo que quede de los 64 MB de entrada.
- **Con su nombre.** El documento llega al guion con el nombre de la URL final, extensión
  incluida, porque pandas elige el motor por ella.

### Lo que el guion ve

**Nada distinto.** El documento le llega como `file_path`, el mismo camino por el que llega un
fichero subido a mano. Su protocolo no cambia y lo que el auditor le permite tampoco:
`requests`, `urllib` y `socket` **siguen denegados**.

Eso no es una comodidad, es la garantía: quien baja es la plataforma, la red del sandbox sigue
cerrada, y la lista blanca se comprueba fuera del proceso donde corre el código del usuario. El
razonamiento completo está en §4.

### Lo que no hace

- **No se puede pedir una URL a mitad de ejecución.** Bajar una página, buscar enlaces dentro y
  bajar ésos son **dos rondas**: la primera devuelve los enlaces, la segunda los pide. Afecta al
  caso de las subvenciones nominativas.
- **Una función empaquetada no acepta `urls`**: corre en el proceso del servidor y se trae lo
  que necesita por su cuenta. Se rechaza en vez de ignorarlo.
- **No se escribe nada hacia fuera.** Sólo `GET`, y sólo `https`: un documento en claro se
  puede alterar por el camino.

---

## 8. Ejecutar una función por API

Para una aplicación externa. Requiere un PAT con el scope `funciones:execute` (lo puede emitir un
superadministrador o un administrador de organización).

```
POST /api/v1/funciones/{funcion_id}/run
{
  "version": 1,
  "ficheros": {"gastos": "ingestion/2026/gastos.xlsx"},
  "parametros": {"umbral": 1000}
}
```

Cuatro cosas que esta superficie **no** relaja:

* **`version` es obligatoria.** El anclaje también rige fuera: una API que ejecutara «la última»
  convertiría cada publicación en un cambio silencioso para todos sus consumidores.
* **La organización se deriva del PAT**, no del cuerpo. Solo funciones propias o publicadas.
* **Una versión suspendida devuelve `423` con el motivo**, no un 404: la función existe y tienes
  que poder distinguir «no está» de «está detenida, y por esto».
* **Los ficheros van por referencia de almacenamiento, no por contenido.** Hay un tope de tamaño
  de petición, heredado del que fijó VAS.1.

Cada ejecución deja un evento en el registro de actividad de IA con la finalidad y las categorías
**que la función declaró** —no las que diga quien llama— y la referencia `funcion:<id>@<v>#<sha>`.
**Sin payloads**, como todo el registro.

La respuesta incluye un bloque `funcion` con qué se ejecutó exactamente, para que puedas anotarlo
en tu propio registro y que los dos se puedan cruzar.

---

## 9. El puente a Fase 3

El catálogo se diseñó como pieza compartida, no solo para informes. En Fase 3, las **acciones de
fase de expediente** referencian `plantilla@versión` y `función@versión` en vez de llevar su
propio código: la restricción está escrita en `planificacion/Plan_TDD_Fase3.md`, donde se retiró
`ejecuciones_accion.codigo_ejecutado` precisamente porque duplicaba sandbox, auditoría y
aprobación.

Lo que se comparte entre módulos es **código y contrato**, nunca datos. Y la cadena
auditoría + sandbox + revisión no se relaja para el nuevo consumidor.

---

## Documentos relacionados

- `docs/ESPECIFICACIONES.md` — qué garantiza la plataforma y en qué madurez.
- `docs/REDACCION_CONTRACT_FIRST.md` — el contrato de plantillas y bloques.
- `docs/MULTITENENCIA.md` — el ámbito de cada tabla, incluidas `hub_funciones` y
  `hub_funcion_versiones`.
- `planificacion/fase1/71_BLOQUE_FUN.md` — los siete prompts con su razonamiento.
