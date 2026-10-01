"""Utilidades de uso directo: lo que hoy se hace fuera, hecho aquí (tema 9 de `ROADMAP.md`).

Deploy: edge — procesa documentos del cliente.
Módulo: utilidades

Operaciones sueltas sobre un fichero que alguien tiene en el escritorio. Hoy se hacen en webs
que no aseguran el RGPD; lo que la plataforma aporta no es la capacidad sino el trayecto.

**Tres reglas, y las tres son el argumento de estas utilidades:**

* **Nada se guarda.** El fichero entra en la petición y sale en la respuesta, en memoria: no hay
  `StorageService` ni disco de por medio, así que no queda nada que borrar ni ningún plazo que
  cumplir. Una utilidad que existe para que el documento no salga no puede convertirse en un
  archivo de documentos ajenos.
* **Queda constancia, y sólo de metadatos** (decisión del usuario, 2026-10-01): quién, cuándo,
  qué operación, cuántos ficheros, páginas o filas. **Nunca el nombre del fichero ni su
  contenido**, que es el criterio del bloque REG; el nombre de un expediente ya dice de quién es.
  El `payload_hash` es la huella de lo que entró, para poder decir después «este fichero pasó por
  aquí» sin guardarlo.
* **Quien no tiene una organización no opera.** El registro va por organización y su columna no
  admite nulo: operar sin anotar sería un uso sin rastro.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import io
import json
import secrets
import zipfile
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.core.uploads import (
    UploadKind,
    read_within_limit,
    sanitizar_nombre,
    validate_upload,
)
from server.app.modules.agents_hub.contracts.actividad import ActividadIAEvent
from server.app.modules.agents_hub.database.operational_models import HubActividadIA
from server.app.modules.utilidades import anonimizar, pdf

router = APIRouter(
    prefix="/utilidades",
    tags=["utilidades"],
    dependencies=[Depends(require_module("utilidades"))],
)

#: Cuántos ficheros como mucho en una operación. Unir veinte anexos es un caso real; más es otra
#: cosa, y sin tope la primera persona que suba cien tumba el contenedor.
MAXIMO_FICHEROS = 20

#: Cuánto pueden pesar entre todos, en bytes. Todo va en memoria, así que esto es lo que la
#: utilidad puede costarle al proceso por petición.
MAXIMO_BYTES_TOTAL = 50 * 1024 * 1024


# =============================================================================
#  Lo común
# =============================================================================


def _organizacion(user: UserInfo):
    organizacion = organizacion_unica_de(user)
    if organizacion is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORGANIZACION_INDETERMINADA",
                "message": (
                    "Estas utilidades anotan cada uso en el registro de tu organización, y tu "
                    "cuenta no pertenece a una sola. Entra con una cuenta de una organización."
                ),
            },
        )
    return organizacion


async def _leer_pdfs(ficheros: list[UploadFile]) -> list[tuple[str, bytes]]:
    """Los PDF subidos, validados por extensión y firma, con el tope de número y de peso."""
    if len(ficheros) > MAXIMO_FICHEROS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"como mucho {MAXIMO_FICHEROS} ficheros por operación; has subido {len(ficheros)}",
        )
    leidos: list[tuple[str, bytes]] = []
    restante = MAXIMO_BYTES_TOTAL
    for fichero in ficheros:
        buffer = await validate_upload(fichero, kind=UploadKind.PDF, max_bytes=restante)
        buffer.seek(0)
        datos = buffer.read()
        restante -= len(datos)
        leidos.append((sanitizar_nombre(fichero.filename), datos))
    return leidos


def _base(nombre: str) -> str:
    base = nombre.rsplit(".", 1)[0] if "." in nombre else nombre
    return base or "documento"


def _descarga(datos: bytes, nombre: str, media_type: str) -> Response:
    # `filename*` con UTF-8: el nombre puede llevar acentos, y sin esto el navegador lo rompe.
    return Response(
        content=datos,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"},
    )


def _zip(partes: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in partes:
            z.writestr(nombre, datos)
    return buffer.getvalue()


def _huella(*documentos: bytes) -> str:
    h = hashlib.sha256()
    for d in documentos:
        h.update(d)
    return h.hexdigest()


async def anotar_uso(
    session: AsyncSession,
    *,
    user: UserInfo,
    organizacion,
    herramienta: str,
    finalidad: str,
    huella: str,
    categorias_datos: list[str] | None = None,
) -> None:
    """Una fila del registro de actividad, **sólo con metadatos**.

    Se construye el `ActividadIAEvent` para que pase por la misma validación que un uso declarado
    desde fuera —que rechaza cualquier campo de contenido—, y luego se guarda.
    """
    evento = ActividadIAEvent(
        ocurrido_en=datetime.now(timezone.utc),
        actor=user.user_id,
        herramienta=herramienta,
        finalidad=finalidad,
        categorias_datos=categorias_datos or [],
        payload_hash=huella,
    )
    session.add(
        HubActividadIA(
            organizacion_id=organizacion,
            ocurrido_en=evento.ocurrido_en,
            actor=evento.actor,
            herramienta=evento.herramienta,
            finalidad=evento.finalidad,
            categorias_datos=evento.categorias_datos,
            payload_hash=evento.payload_hash,
        )
    )
    await session.commit()


def _sin_hacer(fallo: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fallo))


# =============================================================================
#  PDF (UTL.1, issue #190)
# =============================================================================


@router.post("/pdf/unir", operation_id="unirPdf", response_class=Response)
async def unir_pdf(
    files: list[UploadFile] = File(...),
    optimizar: bool = Form(True),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Une los PDF en el orden en que llegan."""
    organizacion = _organizacion(user)
    leidos = await _leer_pdfs(files)
    documentos = [d for _, d in leidos]
    try:
        unido = await asyncio.to_thread(pdf.unir, documentos, optimizar=optimizar)
        paginas = (await asyncio.to_thread(pdf.info, unido)).paginas
    except (pdf.PdfNoValido, pdf.OperacionNoValida) as fallo:
        raise _sin_hacer(fallo) from fallo

    await anotar_uso(
        session,
        user=user,
        organizacion=organizacion,
        herramienta="utilidades/pdf/unir",
        finalidad=f"Unir {len(documentos)} PDF ({paginas} páginas) sin que salgan de la plataforma",
        huella=_huella(*documentos),
    )
    return _descarga(unido, "unido.pdf", "application/pdf")


@router.post("/pdf/partir", operation_id="partirPdf", response_class=Response)
async def partir_pdf(
    file: UploadFile = File(...),
    modo: Literal["rangos", "paginas", "todas"] = Form(...),
    rangos: str = Form(""),
    optimizar: bool = Form(True),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Parte el PDF: por rangos (un fichero por rango), en páginas sueltas (un fichero) o en todas.

    Un fichero sale como PDF; varios, en un ZIP.
    """
    organizacion = _organizacion(user)
    (nombre, datos), = await _leer_pdfs([file])
    base = _base(nombre)
    try:
        if modo == "rangos":
            partes = await asyncio.to_thread(
                pdf.partir_por_rangos, datos, pdf.leer_rangos(rangos),
                nombre_base=base, optimizar=optimizar,
            )
        elif modo == "paginas":
            paginas = [p for inicio, fin in pdf.leer_rangos(rangos) for p in range(inicio, fin + 1)]
            partes = [
                await asyncio.to_thread(
                    pdf.extraer_paginas, datos, paginas, nombre_base=base, optimizar=optimizar
                )
            ]
        else:
            partes = await asyncio.to_thread(
                pdf.una_por_pagina, datos, nombre_base=base, optimizar=optimizar
            )
    except (pdf.PdfNoValido, pdf.OperacionNoValida) as fallo:
        raise _sin_hacer(fallo) from fallo

    await anotar_uso(
        session,
        user=user,
        organizacion=organizacion,
        herramienta=f"utilidades/pdf/partir:{modo}",
        finalidad=f"Partir un PDF en {len(partes)} fichero(s) sin que salga de la plataforma",
        huella=_huella(datos),
    )
    if len(partes) == 1:
        return _descarga(partes[0][1], partes[0][0], "application/pdf")
    return _descarga(_zip(partes), f"{base}_partido.zip", "application/zip")


@router.post("/pdf/optimizar", operation_id="optimizarPdf", response_class=Response)
async def optimizar_pdf(
    file: UploadFile = File(...),
    nivel: int = Form(3),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Reescribe el PDF para que ocupe menos: 1 limpieza básica … 4 el más agresivo."""
    organizacion = _organizacion(user)
    (nombre, datos), = await _leer_pdfs([file])
    try:
        resultado = await asyncio.to_thread(pdf.optimizar, datos, nivel=nivel)
    except (pdf.PdfNoValido, pdf.OperacionNoValida) as fallo:
        raise _sin_hacer(fallo) from fallo

    await anotar_uso(
        session,
        user=user,
        organizacion=organizacion,
        herramienta=f"utilidades/pdf/optimizar:{nivel}",
        finalidad=(
            f"Optimizar un PDF ({resultado.bytes_original} → {resultado.bytes_final} bytes) sin "
            "que salga de la plataforma"
        ),
        huella=_huella(datos),
    )
    return _descarga(resultado.datos, f"{_base(nombre)}_optimizado.pdf", "application/pdf")


# =============================================================================
#  Anonimizar un fichero (UTL.2, issue #191)
# =============================================================================

_MEDIA_TYPE = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class ColumnaPropuesta(BaseModel):
    columna: str
    tipo: str
    modo: str
    modos_posibles: list[str]
    confianza: float
    ejemplos: list[str]


class AnalisisDeFichero(BaseModel):
    formato: str
    filas: int
    #: Del Excel se lee la primera hoja; si hay más, la pantalla lo dice.
    hojas: int
    columnas: list[ColumnaPropuesta]
    #: Los tipos que se pueden elegir, con las reglas de cada uno: el formulario sale de aquí.
    tipos: dict[str, list[str]]
    #: La de esta sesión de trabajo: la vista previa y la descarga la usan, y por eso coinciden.
    semilla: int


class VistaPrevia(BaseModel):
    columnas: list[str]
    antes: list[list[str]]
    despues: list[list[str]]


async def _leer_tabla(file: UploadFile) -> tuple[anonimizar.Tabla, bytes, str]:
    datos = await read_within_limit(file, max_bytes=MAXIMO_BYTES_TOTAL)
    nombre = sanitizar_nombre(file.filename)
    try:
        tabla = await asyncio.to_thread(anonimizar.leer_tabla, datos, nombre)
    except anonimizar.FicheroNoValido as fallo:
        raise _sin_hacer(fallo) from fallo
    return tabla, datos, nombre


def _reglas(texto: str) -> dict[str, anonimizar.Regla]:
    try:
        crudas = json.loads(texto)
        return {col: anonimizar.Regla(r["tipo"], r["modo"]) for col, r in crudas.items()}
    except (ValueError, TypeError, KeyError, AttributeError) as fallo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "las reglas no se entienden: tienen que ser un objeto con, por cada columna, "
                '{"tipo": …, "modo": …}'
            ),
        ) from fallo


async def _aplicar(tabla: anonimizar.Tabla, reglas, semilla: int):
    try:
        return await asyncio.to_thread(anonimizar.aplicar, tabla.df, reglas, semilla=semilla)
    except anonimizar.ReglaNoValida as fallo:
        raise _sin_hacer(fallo) from fallo


@router.post(
    "/anonimizar/analizar", operation_id="analizarFicheroParaAnonimizar",
    response_model=AnalisisDeFichero,
)
async def analizar_fichero(
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user),
) -> AnalisisDeFichero:
    """Propone, para cada columna, qué parece y qué regla aplicarle. No aplica nada."""
    tabla, _datos, _nombre = await _leer_tabla(file)
    propuestas = await asyncio.to_thread(anonimizar.analizar, tabla)
    return AnalisisDeFichero(
        formato=tabla.formato,
        filas=len(tabla.df),
        hojas=tabla.hojas,
        columnas=[
            ColumnaPropuesta(
                columna=p.columna, tipo=p.tipo, modo=p.modo,
                modos_posibles=list(p.modos_posibles), confianza=p.confianza, ejemplos=p.ejemplos,
            )
            for p in propuestas
        ],
        tipos={
            "NONE": [anonimizar.NINGUNO],
            **{t: [*m, anonimizar.NINGUNO] for t, m in anonimizar.MODOS_POR_TIPO.items()},
        },
        semilla=secrets.randbelow(2**31),
    )


@router.post(
    "/anonimizar/vista-previa", operation_id="vistaPreviaAnonimizacion",
    response_model=VistaPrevia,
)
async def vista_previa_anonimizacion(
    file: UploadFile = File(...),
    reglas: str = Form(...),
    semilla: int = Form(...),
    user: UserInfo = Depends(get_current_user),
) -> VistaPrevia:
    """Las primeras filas, antes y después. Se anonimiza el fichero entero, como en la descarga."""
    tabla, _datos, _nombre = await _leer_tabla(file)
    resultado = await _aplicar(tabla, _reglas(reglas), semilla)
    return VistaPrevia(
        columnas=[str(c) for c in tabla.df.columns],
        antes=anonimizar.filas(tabla.df),
        despues=anonimizar.filas(resultado),
    )


@router.post(
    "/anonimizar/descargar", operation_id="descargarAnonimizado", response_class=Response
)
async def descargar_anonimizado(
    file: UploadFile = File(...),
    reglas: str = Form(...),
    semilla: int = Form(...),
    revisado: bool = Form(False),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """El fichero anonimizado, en su formato. **Sólo si se confirma haber revisado la vista previa.**

    El detector no lo ve todo y un falso negativo aquí es un dato personal publicado: la revisión
    humana no es opcional, y el servidor no lo deja en manos de la pantalla.
    """
    organizacion = _organizacion(user)
    if not revisado:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "antes de descargar hay que confirmar que se ha revisado la vista previa: el "
                "detector no lo ve todo, y lo que se le escape saldrá con el fichero"
            ),
        )
    tabla, datos, nombre = await _leer_tabla(file)
    aplicadas = _reglas(reglas)
    resultado = await _aplicar(tabla, aplicadas, semilla)
    salida = await asyncio.to_thread(anonimizar.escribir, resultado, tabla)

    usadas = [r for r in aplicadas.values() if r.modo != anonimizar.NINGUNO]
    resumen = collections.Counter(f"{r.tipo}→{r.modo}" for r in usadas)
    await anotar_uso(
        session,
        user=user,
        organizacion=organizacion,
        herramienta=f"utilidades/anonimizar:{tabla.formato}",
        finalidad=(
            f"Anonimizar un fichero de {len(tabla.df)} filas para compartirlo: "
            + (", ".join(f"{k} ×{n}" for k, n in sorted(resumen.items())) or "ninguna columna")
        ),
        huella=_huella(datos),
        categorias_datos=sorted(
            {anonimizar.CATEGORIA_POR_TIPO[r.tipo] for r in usadas if r.tipo in anonimizar.CATEGORIA_POR_TIPO}
        ),
    )
    return _descarga(salida, f"{_base(nombre)}_anonimizado.{tabla.formato}", _MEDIA_TYPE[tabla.formato])
