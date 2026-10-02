"""El índice de un agente de unidad: cargarlo y seleccionar sobre él (#173).

Deploy: edge.

**Un documento, una ficha.** El asistente general lee el documento entero, así que no hace falta
trocear: la selección es sobre resúmenes, y lo que devuelve son URL. La plataforma no guarda ni
un documento.

Tres reglas que vienen del corpus normativo, y por las mismas razones:

* **La carga es el estado completo.** Un delta por fecha no expresa una baja; aquí una ficha que
  deja de venir se retira. El incremento se calcula en destino, por huella.
* **El vector es del título y el resumen.** Los metadatos y la vigencia no entran en el texto
  embebido: cambiarlos cuesta un `UPDATE`, no re-embeber (regla 5 de AGENTS.md).
* **La vigencia va en el `WHERE`**, y el presupuesto es el `LIMIT`: una ficha descartada después
  del top-k ya habría gastado una plaza.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agentes.acciones import lo_puede_usar
from server.app.modules.agents_hub.database.operational_models import HubAgenteFicha, HubAgenteUnidad
from server.app.modules.agents_hub.services.embedding_service import embed_para_indexar

#: Cuántas fichas como mucho en una carga. Un agente de unidad con más documentos que esto ya no
#: es un agente de unidad, y sin tope una hoja equivocada embebe miles de filas.
MAXIMO_FICHAS = 2000
MAXIMO_TITULO = 500
MAXIMO_RESUMEN = 8000


class IndiceNoValido(ValueError):
    """La hoja no se puede cargar. **No se carga a medias**: el mensaje dice qué fila y por qué."""


class AgenteNoDisponible(PermissionError):
    """El agente no se le ofrece a quien pregunta: suspendido, retirado o fuera de su colectivo."""


class IndiceDeOtroModelo(RuntimeError):
    """El índice se embebió con otro modelo. Comparar vectores de dos modelos no da error y no
    significa nada, así que se para y se dice."""


@dataclass
class FichaEntrada:
    url: str
    titulo: str
    resumen: str
    vigente: bool = True
    revision_prevista_en: date | None = None
    metadatos: dict[str, Any] = field(default_factory=dict)
    version_prompt_resumen: str | None = None
    modelo_resumen: str | None = None


@dataclass(frozen=True)
class InformeDeCarga:
    nuevas: int
    actualizadas: int
    sin_cambios: int
    retiradas: int


@dataclass(frozen=True)
class FichaSeleccionada:
    url: str
    titulo: str
    score: float
    revision_vencida: bool


# =============================================================================
#  Cargar
# =============================================================================


def texto_embebido(ficha: FichaEntrada) -> str:
    """Lo único que se embebe: estructura estable, nunca etiquetas."""
    return f"{ficha.titulo}\n\n{ficha.resumen}"


def _sha(valor: Any) -> str:
    return hashlib.sha256(
        json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _huella(ficha: FichaEntrada) -> str:
    return _sha(
        [
            ficha.titulo,
            ficha.resumen,
            ficha.vigente,
            ficha.revision_prevista_en,
            ficha.metadatos,
            ficha.version_prompt_resumen,
            ficha.modelo_resumen,
        ]
    )


def validar(fichas: list[FichaEntrada]) -> list[FichaEntrada]:
    """Comprueba la hoja entera antes de tocar nada. La fila se cuenta como en la hoja: la 2 es la
    primera de datos, porque la 1 es la cabecera."""
    if len(fichas) > MAXIMO_FICHAS:
        raise IndiceNoValido(
            f"como mucho {MAXIMO_FICHAS} fichas por agente; la hoja trae {len(fichas)}"
        )
    vistas: dict[str, int] = {}
    limpias: list[FichaEntrada] = []
    for i, f in enumerate(fichas, start=2):
        url = (f.url or "").strip()
        titulo = (f.titulo or "").strip()
        resumen = (f.resumen or "").strip()
        if not url.startswith("https://"):
            raise IndiceNoValido(f"fila {i}: la URL tiene que ser https del almacén ({url or 'vacía'})")
        if url in vistas:
            raise IndiceNoValido(f"fila {i}: la URL está repetida (ya estaba en la fila {vistas[url]})")
        if not titulo:
            raise IndiceNoValido(f"fila {i}: falta el título")
        if not resumen:
            raise IndiceNoValido(f"fila {i}: falta el resumen, que es sobre lo que se selecciona")
        if len(titulo) > MAXIMO_TITULO or len(resumen) > MAXIMO_RESUMEN:
            raise IndiceNoValido(
                f"fila {i}: el título no puede pasar de {MAXIMO_TITULO} caracteres ni el resumen "
                f"de {MAXIMO_RESUMEN}"
            )
        vistas[url] = i
        limpias.append(
            FichaEntrada(
                url=url,
                titulo=titulo,
                resumen=resumen,
                vigente=bool(f.vigente),
                revision_prevista_en=f.revision_prevista_en,
                metadatos=dict(f.metadatos or {}),
                version_prompt_resumen=(f.version_prompt_resumen or None),
                modelo_resumen=(f.modelo_resumen or None),
            )
        )
    return limpias


async def cargar(
    session: AsyncSession, agente_id: uuid.UUID, fichas: list[FichaEntrada], embedder: Any
) -> InformeDeCarga:
    """Deja el índice del agente **igual que la hoja**: crea, actualiza, deja y retira.

    Sólo embebe lo nuevo y aquello cuyo título o resumen cambió. Si falla el embebido, no se ha
    escrito nada: la sesión no se commitea.
    """
    entrada = validar(fichas)
    # Una carga a la vez por agente: sin esto, dos cargas simultáneas —el guion y una persona—
    # leían el mismo índice, las dos insertaban, y una moría en la restricción única. La segunda
    # espera aquí a que la primera commitee y ve lo que dejó.
    await session.execute(
        select(HubAgenteUnidad.id).where(HubAgenteUnidad.id == agente_id).with_for_update()
    )
    existentes = {
        f.url: f
        for f in (
            await session.execute(select(HubAgenteFicha).where(HubAgenteFicha.agente_id == agente_id))
        ).scalars()
    }

    por_embeber: list[FichaEntrada] = [
        f
        for f in entrada
        if f.url not in existentes
        or existentes[f.url].huella_embebida != _sha(texto_embebido(f))
        or existentes[f.url].embedding_model != embedder.model_name
    ]
    vectores = dict(
        zip(
            (f.url for f in por_embeber),
            await embed_para_indexar(embedder, [texto_embebido(f) for f in por_embeber]),
        )
    )

    ahora = datetime.now(timezone.utc)
    nuevas = actualizadas = sin_cambios = 0
    for f in entrada:
        fila = existentes.get(f.url)
        if fila is not None and fila.huella == _huella(f) and f.url not in vectores:
            sin_cambios += 1
            continue
        if fila is None:
            fila = HubAgenteFicha(agente_id=agente_id, url=f.url, created_at=ahora)
            session.add(fila)
            nuevas += 1
        else:
            actualizadas += 1
        fila.titulo = f.titulo
        fila.resumen = f.resumen
        fila.vigente = f.vigente
        fila.revision_prevista_en = f.revision_prevista_en
        fila.metadatos = f.metadatos
        fila.version_prompt_resumen = f.version_prompt_resumen
        fila.modelo_resumen = f.modelo_resumen
        fila.huella = _huella(f)
        fila.updated_at = ahora
        if f.url in vectores:
            fila.embedding = vectores[f.url]
            fila.embedding_model = embedder.model_name
            fila.huella_embebida = _sha(texto_embebido(f))

    urls = {f.url for f in entrada}
    retirar = [url for url in existentes if url not in urls]
    if retirar:
        await session.execute(
            delete(HubAgenteFicha).where(
                HubAgenteFicha.agente_id == agente_id, HubAgenteFicha.url.in_(retirar)
            )
        )
    await session.commit()
    return InformeDeCarga(nuevas, actualizadas, sin_cambios, len(retirar))


# =============================================================================
#  Seleccionar
# =============================================================================


async def seleccionar(
    session: AsyncSession,
    agente: Any,
    version: Any,
    consulta: str,
    embedder: Any,
    *,
    principal: Any,
) -> list[FichaSeleccionada]:
    """Los documentos pertinentes para la consulta, **nunca más que el presupuesto del agente**.

    El acotado por colectivo es del agente —la consulta nombra uno—, así que se comprueba antes;
    la vigencia es de cada ficha y va en el `WHERE`.
    """
    if not lo_puede_usar(agente, version, principal=principal):
        raise AgenteNoDisponible("este agente no se te ofrece")

    modelos = set(
        (
            await session.execute(
                select(HubAgenteFicha.embedding_model)
                .where(HubAgenteFicha.agente_id == agente.id)
                .distinct()
            )
        ).scalars()
    )
    if not modelos:
        return []
    if modelos != {embedder.model_name}:
        raise IndiceDeOtroModelo(
            f"el índice se embebió con {', '.join(sorted(modelos))} y la plataforma usa ahora "
            f"{embedder.model_name}: hay que volver a cargarlo"
        )

    vector = await embedder.embed(consulta)
    distancia = HubAgenteFicha.embedding.cosine_distance(vector).label("distancia")
    filas = (
        await session.execute(
            select(HubAgenteFicha, distancia)
            .where(HubAgenteFicha.agente_id == agente.id, HubAgenteFicha.vigente.is_(True))
            .order_by(distancia)
            .limit(version.presupuesto_documentos)
        )
    ).all()
    hoy = date.today()
    return [
        FichaSeleccionada(
            url=f.url,
            titulo=f.titulo,
            score=round(1.0 - float(d), 4),
            revision_vencida=f.revision_prevista_en is not None and hoy > f.revision_prevista_en,
        )
        for f, d in filas
    ]


# =============================================================================
#  La hoja
# =============================================================================


def _clave(cabecera: Any) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(cabecera)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")


#: Cómo se llaman las columnas que la plataforma entiende. Lo demás va a metadatos tal cual.
_COLUMNAS = {
    "url": "url",
    "titulo": "titulo",
    "resumen": "resumen",
    "vigente": "vigente",
    "vigencia": "vigente",
    "revision_prevista_en": "revision_prevista_en",
    "revision_prevista": "revision_prevista_en",
    "fecha_de_revision": "revision_prevista_en",
    "version_prompt_resumen": "version_prompt_resumen",
    "modelo_resumen": "modelo_resumen",
}

_SI = {"", "si", "s", "true", "1", "x", "vigente", "yes"}
_NO = {"no", "n", "false", "0", "no_vigente", "derogado", "derogada", "superado", "superada"}


def _vacio(valor: Any) -> bool:
    if valor is None:
        return True
    try:
        import pandas as pd

        if pd.isna(valor):
            return True
    except (TypeError, ValueError):
        pass
    return str(valor).strip() == ""


def _vigente(valor: Any, fila: int) -> bool:
    if isinstance(valor, bool):
        return valor
    clave = "" if _vacio(valor) else _clave(valor)
    if clave in _SI:
        return True
    if clave in _NO:
        return False
    raise IndiceNoValido(f"fila {fila}: no se entiende la vigencia «{valor}»; vale «sí» o «no»")


def _fecha(valor: Any, fila: int) -> date | None:
    if _vacio(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    raise IndiceNoValido(f"fila {fila}: no se entiende la fecha de revisión «{valor}»")


def desde_tabla(df: Any) -> list[FichaEntrada]:
    """La hoja del guion de curación, o la que prepara la unidad a mano, como fichas."""
    columnas = {c: _COLUMNAS.get(_clave(c)) for c in df.columns}
    if "url" not in columnas.values():
        raise IndiceNoValido("la hoja no tiene columna «url»: es lo que identifica cada documento")
    fichas: list[FichaEntrada] = []
    for i, registro in enumerate(df.to_dict(orient="records"), start=2):
        datos: dict[str, Any] = {}
        metadatos: dict[str, str] = {}
        for original, valor in registro.items():
            destino = columnas[original]
            if destino is None:
                if not _vacio(valor):
                    metadatos[str(original)] = str(valor).strip()
                continue
            datos[destino] = valor
        fichas.append(
            FichaEntrada(
                url="" if _vacio(datos.get("url")) else str(datos["url"]).strip(),
                titulo="" if _vacio(datos.get("titulo")) else str(datos["titulo"]).strip(),
                resumen="" if _vacio(datos.get("resumen")) else str(datos["resumen"]).strip(),
                vigente=_vigente(datos.get("vigente"), i),
                revision_prevista_en=_fecha(datos.get("revision_prevista_en"), i),
                metadatos=metadatos,
                version_prompt_resumen=None
                if _vacio(datos.get("version_prompt_resumen"))
                else str(datos["version_prompt_resumen"]).strip(),
                modelo_resumen=None
                if _vacio(datos.get("modelo_resumen"))
                else str(datos["modelo_resumen"]).strip(),
            )
        )
    return fichas
