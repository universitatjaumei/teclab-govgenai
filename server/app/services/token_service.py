"""
Servicio de auditoría y registro de consumo de tokens.

Gestiona el historial detallado de solicitudes de IA, permitiendo la migración
desde sistemas legacy (CSV) y la generación de estadísticas agregadas para
análisis financiero.
"""

import logging
from datetime import datetime
from typing import Optional
from sqlmodel import select, desc
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.database.db import server_engine
from server.app.database.models import TokenLog
from server.app.services.pricing_service import calculate_cost

import asyncio
from sqlalchemy.exc import OperationalError

# Issue #18 — la migracion del CSV corre al arrancar el servidor, no desde una consola.
logger = logging.getLogger(__name__)


async def log_token_usage(
    script_source: str, provider: str, model: str, input_tokens: int, output_tokens: int
):
    """
    Registra el uso de tokens en la base de datos calculando su coste real.

    Implementa una lógica de reintentos para manejar bloqueos de base de datos
    (SQLite Lock) en entornos de alta concurrencia.

    Args:
        script_source: Nombre o ID del script que realizó la petición.
        provider: Proveedor de IA (ej: 'Google', 'OpenRouter').
        model: Modelo utilizado (ej: 'gemini-1.5-pro').
        input_tokens: Tokens enviados en el prompt.
        output_tokens: Tokens recibidos en la respuesta.
    """
    try:
        cost = await calculate_cost(provider, model, input_tokens, output_tokens)

        log_entry = TokenLog(
            script_source=script_source,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            timestamp=datetime.utcnow(),
        )

        # Retry logic for DB Lock
        max_retries = 5
        for attempt in range(max_retries):
            try:
                async with AsyncSession(server_engine) as session:
                    session.add(log_entry)
                    await session.commit()
                break  # Success
            except OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))  # Backoff
                else:
                    raise e  # Re-raise if not lock or retries exhausted

    except Exception:
        # El consumo de tokens es lo que sostiene la facturacion y las cuotas: perder un
        # registro en silencio es perder dinero sin que nadie lo vea. Con el traceback, al
        # menos se puede saber cuantos y por que.
        logger.exception("No se pudo registrar el consumo de tokens de una llamada")


async def get_token_stats(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    script_filter: Optional[str] = None,
    provider_filter: Optional[str] = None,
):
    """
    Calcula estadísticas agregadas de consumo para un periodo y filtros dados.

    Args:
        start_date: Fecha de inicio de la consulta.
        end_date: Fecha de fin de la consulta.
        script_filter: Filtrar por nombre de script específico.
        provider_filter: Filtrar por proveedor específico.

    Returns:
        Dict: Resumen con coste total, tokens totales y lista de logs recientes.
    """
    async with AsyncSession(server_engine) as session:
        query = select(TokenLog).order_by(desc(TokenLog.timestamp))

        if start_date:
            query = query.where(TokenLog.timestamp >= start_date)
        if end_date:
            query = query.where(TokenLog.timestamp <= end_date)
        if script_filter and script_filter != "All":
            query = query.where(TokenLog.script_source == script_filter)
        if provider_filter and provider_filter != "All":
            query = query.where(TokenLog.provider == provider_filter)

        result = await session.exec(query)
        logs = result.all()

        total_cost = sum(log_item.cost for log_item in logs)
        total_tokens = sum(log_item.input_tokens + log_item.output_tokens for log_item in logs)

        return {
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "logs": logs[:500],  # Limit to 500 recent for UI
        }
