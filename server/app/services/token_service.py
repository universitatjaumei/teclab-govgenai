"""
Servicio de auditoría y registro de consumo de tokens.

Gestiona el historial detallado de solicitudes de IA, permitiendo la migración
desde sistemas legacy (CSV) y la generación de estadísticas agregadas para
análisis financiero.
"""

import csv
import logging
import os
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


async def migrate_csv_logs():
    """
    Importa registros históricos desde archivos CSV hacia la base de datos SQL.

    Verifica si la base de datos ya contiene datos para evitar duplicados y
    realiza la importación en lotes, recalculando los costes con el service
    de pricing actual.
    """
    csv_path = os.path.join(os.getcwd(), "token_usage_log.csv")
    if not os.path.exists(csv_path):
        return

    logger.info("Migrando el historial de tokens desde el CSV")

    try:
        # Check if DB is already populated to avoid duplicates (naive check)
        async with AsyncSession(server_engine) as session:
            result = await session.exec(select(TokenLog).limit(1))
            if result.first():
                logger.info(
                    "La base ya tiene historial de tokens: no se migra el CSV"
                )
                return

        new_logs = []
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # CSV format: Fecha,Script,Proveedor,Modelo,Tokens_Enviados,Tokens_Recibidos
                    timestamp_str = row.get("Fecha")
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    provider = row.get("Proveedor")
                    model = row.get("Modelo")
                    input_tokens = int(row.get("Tokens_Enviados", 0))
                    output_tokens = int(row.get("Tokens_Recibidos", 0))

                    # Estimate cost for historical data?
                    # Note: We might be calculating cost with FUTURE prices, but better than 0.
                    # We can't await inside this sync loop easily unless we collect and process.

                    new_logs.append(
                        {
                            "timestamp": timestamp,
                            "script_source": row.get("Script"),
                            "provider": provider,
                            "model": model,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        }
                    )

                except ValueError:
                    continue

        # Process in batches or one go
        async with AsyncSession(server_engine) as session:
            count = 0
            for log_data in new_logs:
                # Calculate cost (now we can await)
                cost = await calculate_cost(
                    log_data["provider"],
                    log_data["model"],
                    log_data["input_tokens"],
                    log_data["output_tokens"],
                )

                db_log = TokenLog(
                    timestamp=log_data["timestamp"],
                    script_source=log_data["script_source"],
                    provider=log_data["provider"],
                    model=log_data["model"],
                    input_tokens=log_data["input_tokens"],
                    output_tokens=log_data["output_tokens"],
                    cost=cost,
                )
                session.add(db_log)
                count += 1

            await session.commit()
            logger.info("Migrados %d registros de tokens desde el CSV", count)

            # Optional: rename CSV to backup?
            # os.rename(csv_path, csv_path + ".bak")

    except Exception:
        logger.exception("Fallo la migracion del historial de tokens desde el CSV")


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
