"""Las guardas del catálogo de funciones (FUN.1).

Deploy: edge — el código y la declaración de una función de autoservicio son de la organización.

Tres reglas viven aquí y no en la base, y cada una por su motivo:

1. **La coherencia por origen** son cuatro reglas cruzadas entre dos tablas (`autoservicio` exige
   código, finalidad y quién declara; `paquete` exige *entry point* y semver y **prohíbe**
   código). Un `CheckConstraint` podría expresar parte, pero no puede decir *qué falta*, y es
   justo lo que necesita quien está rellenando el formulario.
2. **La inmutabilidad de una versión registrada.** Corregir es publicar otra versión: el código de
   una versión registrada no se edita jamás, por la misma razón que no se edita un registro de
   auditoría. Sin ella, «arreglar una vez» sería «cambiar en silencio informes ya aprobados».
3. **El motivo al suspender.** El bloque anclado a una versión suspendida falla en alto *con el
   motivo* (FUN.3); sin motivo, ese fallo no podría explicarse. Suspender es de quien revisa y
   retirar es de quien escribe: dos responsabilidades distintas de la matriz de la Instrucció §9.

Nada de esto sabe de «informe»: el catálogo es una pieza compartida y en Fase 3 lo consumen las
fases de expediente.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

#: Los campos que **sí** se pueden escribir sobre una versión que ya no es borrador: son de otra
#: persona y de otro momento —la revisión posterior y la suspensión de la Instrucció §8.4— y no
#: cambian lo que se ejecuta.
CAMPOS_POSTERIORES: frozenset[str] = frozenset({
    "estado",
    "revisada_por",
    "revisada_en",
    "revision_resultado",
    "revision_nota",
    "suspendida_por",
    "suspendida_en",
    "motivo_suspension",
})

#: Estados en los que una versión ya no admite cambios de contenido.
ESTADOS_CERRADOS: frozenset[str] = frozenset(
    {"registrada", "suspendida", "retirada", "no_instalada"}
)


class FuncionIncoherente(ValueError):
    """Los datos de una versión no encajan con su origen, o falta la declaración responsable."""


class VersionInmutable(RuntimeError):
    """Se ha intentado cambiar el contenido de una versión que ya no es un borrador."""


def sha256_del_codigo(code: str) -> str:
    """El hash de lo que va a ejecutarse, que es lo que el `RunManifest` registra.

    Se calcula al escribir y no lo aporta quien llama: un hash que viniera de fuera podría no
    corresponder al código, y entonces el manifiesto diría que corrió algo que no corrió.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def datos_de_version_coherentes(
    *,
    origen: str,
    code: str | None = None,
    finalidad: str | None = None,
    declarada_por: uuid.UUID | None = None,
    categorias_datos: list[str] | None = None,
    version_paquete: str | None = None,
    entry_point: str | None = None,
    entorno_ejecucion: str | None = None,
) -> None:
    """Comprueba la forma de una versión según su origen. Levanta `FuncionIncoherente`.

    El mensaje dice **qué falta**, porque esto se ve en un formulario: «falta el código» es
    accionable y «datos incoherentes» no lo es.
    """
    if origen == "autoservicio":
        if not code or not code.strip():
            raise FuncionIncoherente(
                "una función de autoservicio necesita su código: es lo que se audita y lo que "
                "corre en el sandbox"
            )
        if not finalidad or not finalidad.strip():
            raise FuncionIncoherente(
                "falta la finalidad de la declaración responsable, que la Instrucció 02/2026 "
                "exige registrar antes de compartir (§8.2)"
            )
        if declarada_por is None:
            raise FuncionIncoherente(
                "falta quién declara: una declaración responsable sin responsable no es una "
                "declaración"
            )
        if version_paquete is not None:
            raise FuncionIncoherente(
                "una función de autoservicio no tiene versión de paquete: su versionado es el "
                "ordinal del catálogo"
            )
        return

    if origen == "paquete":
        if code is not None:
            raise FuncionIncoherente(
                "una función empaquetada no guarda su código aquí: vive en el paquete, y una "
                "copia divergiría del `pip install` sin que nada avisara"
            )
        if not version_paquete:
            raise FuncionIncoherente(
                "falta la versión (semver) de la distribución instalada"
            )
        if not entry_point:
            raise FuncionIncoherente(
                "falta el punto de entrada «distribucion:nombre» que identifica la función"
            )
        return

    if origen == "externa":
        # AUT.3 — un cuaderno o un script que se ejecuta **fuera**. Lo que la plataforma guarda
        # es el fichero y su hash, que hace de versión, más la declaración responsable y dónde
        # corre. No hay contrato de sandbox que cumplir porque no lo va a ejecutar.
        if not code or not code.strip():
            raise FuncionIncoherente(
                "una función externa necesita su fichero: el hash del fichero es lo que hace "
                "de versión, así que sin él no hay nada que registrar ni que versionar"
            )
        if not finalidad or not finalidad.strip():
            raise FuncionIncoherente(
                "falta la finalidad de la declaración responsable, que la Instrucció 02/2026 "
                "exige registrar antes de compartir (§8.2)"
            )
        if declarada_por is None:
            raise FuncionIncoherente(
                "falta quién declara: una declaración responsable sin responsable no es una "
                "declaración"
            )
        if not entorno_ejecucion or not entorno_ejecucion.strip():
            raise FuncionIncoherente(
                "falta decir dónde se ejecuta: la plataforma no lo ejecuta, así que sin eso el "
                "registro no dice de qué responde nadie ni con qué credenciales se toca el dato"
            )
        if version_paquete is not None or entry_point is not None:
            raise FuncionIncoherente(
                "una función externa no se instala ni se descubre por punto de entrada: se "
                "registra su fichero. Si viene de un paquete, su origen es «paquete»"
            )
        return

    raise FuncionIncoherente(
        f"«{origen}» no es un origen conocido; los que hay son autoservicio, paquete y externa"
    )


def asegurar_editable(version: Any, cambios: dict[str, Any]) -> None:
    """Deja pasar los cambios admisibles sobre una versión, o levanta.

    Un borrador se edita entero. Una versión cerrada sólo admite los campos de la revisión
    posterior y de la suspensión — y suspender, además, exige motivo.
    """
    estado_actual = getattr(version, "estado", "draft")

    if estado_actual not in ESTADOS_CERRADOS:
        _exigir_motivo_al_suspender(version, cambios)
        return

    de_contenido = sorted(set(cambios) - CAMPOS_POSTERIORES)
    if de_contenido:
        raise VersionInmutable(
            f"una versión en estado «{estado_actual}» no cambia "
            f"{', '.join(de_contenido)}: corregir es publicar una versión nueva"
        )

    _exigir_motivo_al_suspender(version, cambios)


def _exigir_motivo_al_suspender(version: Any, cambios: dict[str, Any]) -> None:
    if cambios.get("estado") != "suspendida":
        return
    motivo = cambios.get("motivo_suspension") or getattr(version, "motivo_suspension", None)
    if not motivo or not str(motivo).strip():
        raise FuncionIncoherente(
            "suspender exige motivo: el bloque anclado a esta versión va a fallar en alto y "
            "tiene que poder decir por qué"
        )


async def registrar_version(
    session: Any,
    *,
    nombre: str,
    organizacion_id: uuid.UUID | None,
    code: str,
    contrato: Any,
    declarada_por: uuid.UUID,
    audit_result: dict[str, Any] | None = None,
    autoria: str = "ia",
    funcion_id: uuid.UUID | None = None,
    creada_por: uuid.UUID | None = None,
    origen: str = "autoservicio",
    entorno_ejecucion: str | None = None,
) -> tuple[Any, Any]:
    """Registra una versión en el catálogo y la deja **usable de inmediato** (FUN.3).

    Esto es lo que sustituye a la aprobación como puerta. La Instrucció 02/2026 prohíbe la
    aprobación humana previa como condición para compartir en el nivel 2 (§5), así que el filtro
    es automático —declaración responsable + auditoría sin hallazgos críticos + prueba en
    sandbox, que el llamante ya ha comprobado— y la persona entra **después**, en la revisión
    posterior (FUN.4).

    Con `funcion_id` publica una versión nueva de una función que ya existe; sin él crea la
    función. En los dos casos el ordinal es el siguiente, y **la versión anterior no se toca**:
    es lo que hace que publicar v2 no cambie ninguna plantilla anclada a v1.

    **El filtro previo lo aplica quien llama, y por eso el origen importa** (AUT.3). Para
    `autoservicio` el llamante ya ha comprobado auditoría sin hallazgos críticos y prueba en
    sandbox, porque ese código va a correr aquí. Para `externa` no hay nada que comprobar en ese
    sentido: el código corre fuera, usa red y disco legítimamente, y el auditor pasa con perfil
    **informativo** —sus hallazgos se guardan y van a la cola de revisión, no bloquean—. Exigirle
    las reglas del sandbox a un programa que no va a entrar en él sería, además, aprobación
    previa por la puerta de atrás.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from server.app.modules.redaccion.database.models import (
        HubFuncion,
        HubFuncionVersion,
    )

    datos_de_version_coherentes(
        origen=origen,
        code=code,
        finalidad=contrato.finalidad,
        declarada_por=declarada_por,
        categorias_datos=list(contrato.categorias_datos),
        entorno_ejecucion=entorno_ejecucion,
    )

    if funcion_id is None:
        funcion = HubFuncion(
            # La identidad se asigna al construir y no al hacer `flush`: el defecto de columna
            # sólo lo aplica la base, así que sin esto el objeto vive un rato con `id=None` y
            # cualquiera que lo lea antes del flush —la referencia del bloque, el manifiesto—
            # escribe «None». Es lo que hace el resto de los modelos del módulo.
            id=uuid.uuid4(),
            nombre=nombre,
            descripcion="",
            organizacion_id=organizacion_id,
            origen=origen,
            creada_por=creada_por or declarada_por,
        )
        session.add(funcion)
        await session.flush()
    else:
        funcion = await session.get(HubFuncion, funcion_id)
        if funcion is None:
            raise FuncionIncoherente(
                f"no hay ninguna función {funcion_id} a la que añadir una versión"
            )

    siguiente = (
        await session.execute(
            select(func.coalesce(func.max(HubFuncionVersion.version), 0) + 1).where(
                HubFuncionVersion.funcion_id == funcion.id
            )
        )
    ).scalar_one()

    version = HubFuncionVersion(
        id=uuid.uuid4(),
        funcion_id=funcion.id,
        version=int(siguiente),
        code=code,
        contrato_entrada=contrato.model_dump(mode="json"),
        contrato_salida={"kind": contrato.salida},
        audit_result_json=audit_result,
        code_sha256=sha256_del_codigo(code),
        # Registrada, no aprobada: usable ya, revisable después.
        estado="registrada",
        autoria=autoria,
        finalidad=contrato.finalidad,
        categorias_datos=list(contrato.categorias_datos),
        declarada_por=declarada_por,
        declarada_en=datetime.now(timezone.utc),
        entorno_ejecucion=entorno_ejecucion,
    )
    session.add(version)
    await session.flush()
    return funcion, version


async def ejecutar_funcion(
    *,
    contrato: Any,
    code: str,
    ficheros: dict[str, str] | None = None,
    parametros: dict[str, Any] | None = None,
    sandbox: Any,
    timeout_seconds: int | None = None,
) -> Any:
    """Valida la entrada contra el contrato y **después** ejecuta (FUN.2).

    El orden es la mitad del prompt: con la validación detrás, un ERP que cambia de formato se
    manifiesta como un `KeyError` de pandas dentro de un subproceso; con la validación delante,
    como «falta el slot datos». El espía de los tests comprueba que el sandbox no se toca cuando
    la entrada no cumple.

    **El protocolo del script no cambia** —`file_path`, `raw_text`, `options`—: cambiarlo
    obligaría a reescribir los scripts que ya funcionan, que es lo que empuja al Shadow IT. Los
    parámetros del contrato viajan dentro de `options`, que es donde el script ya los busca.

    La salida se valida como `ExtractionResult`. Con el sandbox real no hace falta —lo construye
    él—, pero en FUN.5 el `run` de un paquete de un tercero devuelve lo que haya escrito ese
    tercero, y la costura tiene que aguantarlo sin reventar de forma opaca.
    """
    from server.app.modules.redaccion.contracts.funciones import validar_entrada
    from server.app.modules.redaccion.pipelines.contracts import (
        ExtractionProvenance,
        ExtractionResult,
        ExtractionWarning,
    )

    entrada = validar_entrada(contrato, ficheros=ficheros, parametros=parametros)

    # El primer slot es el fichero que el protocolo actual pasa como `file_path`; el resto viaja
    # en `options`, que es donde un script que ya funcionaba busca lo suyo.
    primer_slot = contrato.slots[0].slot_id if getattr(contrato, "slots", None) else None
    file_path = entrada.ficheros.get(primer_slot) if primer_slot else None
    options: dict[str, Any] = {**entrada.parametros, "ficheros": entrada.ficheros}

    # AUT.7 — el camino con artefactos **sólo** si el contrato los declara.
    #
    # No es una optimización: `execute_extraction_script` la implementan varios dobles de test
    # y la consume media aplicación, así que preguntar por el contrato antes es lo que hace que
    # nada de lo que ya funcionaba tenga que enterarse de que esto existe.
    declarados = getattr(contrato, "artefactos", None)
    brutos: list[Any] = []
    if declarados is not None and hasattr(sandbox, "execute_extraction_con_artefactos"):
        salida, brutos = await sandbox.execute_extraction_con_artefactos(
            code=code,
            file_path=file_path,
            raw_text=None,
            options=options,
            timeout_seconds=timeout_seconds,
            artefactos_maximo=declarados.maximo,
            artefactos_maximo_bytes=declarados.maximo_bytes,
        )
    else:
        salida = await sandbox.execute_extraction_script(
            code=code,
            file_path=file_path,
            raw_text=None,
            options=options,
            timeout_seconds=timeout_seconds,
        )

    if isinstance(salida, ExtractionResult):
        # El contenido de los ficheros se cuelga **fuera del modelo**, en un atributo del
        # objeto: `ExtractionResult` es el contrato y viaja en respuestas y manifiestos, así
        # que un campo con bytes ahí acabaría devolviendo un Excel dentro de un JSON de
        # metadatos. Quien orquesta lo recoge con `artefactos_en_bruto(...)`.
        _colgar_brutos(salida, brutos)
        return salida

    try:
        return ExtractionResult.model_validate(salida)
    except Exception as fallo:  # noqa: BLE001 — se convierte en aviso, no en excepción opaca
        return ExtractionResult(
            warnings=[
                ExtractionWarning(
                    code="SALIDA_FUERA_DE_CONTRATO",
                    message=(
                        "la función devolvió algo que no cumple el contrato de salida "
                        f"(ExtractionResult): {fallo}"
                    ),
                    severity="error",
                )
            ],
            provenance=ExtractionProvenance(
                pipeline_id="funcion_catalogo",
                source_ref=primer_slot or "",
                extracted_at=datetime.now(timezone.utc),
            ),
        )


def consulta_de_catalogo(*, organizacion_id: uuid.UUID | None):
    """Las funciones que una organización puede ver: las suyas y las publicadas.

    Nunca las no publicadas de otra. Es la misma frontera de siempre, escrita una vez aquí para
    que el router, el resolutor y el catálogo del panel no la escriban cada uno a su manera.

    **Trae su propio orden** (DET.1), y no por doctrina: sin `ORDER BY`, la misma consulta devolvió
    el catálogo en otro orden después de una mutación durante la verificación de FUN.4, y la ficha
    que se estaba leyendo cambió de sitio. En una pantalla con un botón de suspender, cambiar de
    sitio significa pulsar sobre otra fila. El desempate por `id` es la otra mitad: dos funciones
    creadas en el mismo instante —las de una migración— pueden alternarse sin él.
    """
    from sqlalchemy import or_, select

    from server.app.modules.redaccion.database.models import HubFuncion

    publicadas = or_(
        HubFuncion.publicada_en.isnot(None),
        HubFuncion.organizacion_id.is_(None),
    )
    orden = (HubFuncion.created_at, HubFuncion.id)
    if organizacion_id is None:
        # Sin organización sólo se ven las de plataforma: es lo que responde la tenencia a un
        # principal sin organización, y no «todas».
        return select(HubFuncion).where(publicadas).order_by(*orden)

    return (
        select(HubFuncion)
        .where(or_(HubFuncion.organizacion_id == organizacion_id, publicadas))
        .order_by(*orden)
    )


# ── AUT.7: el contenido de los ficheros, de paso ─────────────────────────────────────

#: Dónde se cuelga la lista de `ArtefactoEnBruto` en el `ExtractionResult` que se devuelve.
#:
#: **Va en un atributo y no en un campo del modelo** porque el modelo es el contrato: sale por
#: la API y entra en el manifiesto, y un campo de bytes ahí devolvería el fichero entero dentro
#: de un JSON de metadatos. Pydantic no serializa lo que no declara, así que esto viaja entre
#: `ejecutar_funcion` y quien orquesta y no se cuela en ninguna respuesta.
_ATRIBUTO_DE_BRUTOS = "_artefactos_en_bruto"


def _colgar_brutos(salida: Any, brutos: list[Any]) -> None:
    if brutos:
        object.__setattr__(salida, _ATRIBUTO_DE_BRUTOS, brutos)


def artefactos_en_bruto(salida: Any) -> list[Any]:
    """Los ficheros que la ejecución produjo, con su contenido, o lista vacía.

    Lista vacía y no `None` para que quien orquesta no tenga que distinguir «no produjo» de «no
    declaró»: las dos cosas se guardan igual, que es no guardando nada.
    """
    return list(getattr(salida, _ATRIBUTO_DE_BRUTOS, []) or [])
