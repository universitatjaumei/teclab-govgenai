"""
Servicio de programación de tareas en segundo plano.

Gestiona la actualización periódica de la caché de modelos de IA y los
datos de precios. Es configurable a través de la interfaz de administración
(habilitar/deshabilitar, hora de ejecución).
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.database.db import server_engine
from server.app.database.models import SchedulerConfig

# Issue #18 — el planificador corre DENTRO del servidor, asi que su salida es registro y no
# consola. El prefijo «[Scheduler]» que llevaba cada linea sobra: el nombre del modulo ya va
# en el formato, y la marca de tiempo tambien —varias lineas la repetian a mano—.
logger = logging.getLogger(__name__)


class ModelRefreshScheduler:
    """
    Planificador de tareas (Singleton) para el mantenimiento del servidor.

    Utiliza APScheduler para ejecutar tareas asíncronas de sincronización con
    proveedores externos (OpenRouter, Google) en horarios programados o bajo demanda.
    """

    _instance: Optional["ModelRefreshScheduler"] = None
    _scheduler: Optional[AsyncIOScheduler] = None
    _job_id: str = "model_refresh_job"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler()

    async def _get_config(self) -> SchedulerConfig:
        """
        Recupera o inicializa la configuración del planificador en la base de datos.

        Returns:
            SchedulerConfig: Configuración persistente (hora, minuto, estado).
        """
        async with AsyncSession(server_engine) as session:
            config = await session.get(SchedulerConfig, 1)
            if not config:
                config = SchedulerConfig(id=1)
                session.add(config)
                await session.commit()
                await session.refresh(config)
            return config

    async def _update_last_run(self):
        """Update last run timestamp in DB."""
        async with AsyncSession(server_engine) as session:
            config = await session.get(SchedulerConfig, 1)
            if config:
                config.last_run = datetime.utcnow()
                session.add(config)
                await session.commit()

    async def _refresh_task(self):
        """
        Tarea principal de mantenimiento que se ejecuta según el cron.

        Realiza:
        1. Refresco de la caché de modelos disponibles.
        2. Actualización de precios (USD per million tokens).
        3. Registro de auditoría del último éxito.
        """
        logger.info("Arranca el refresco programado de modelos")

        try:
            # Refresh model cache
            from server.app.services.model_fetcher import refresh_model_cache

            await refresh_model_cache()

            # Update pricing data
            from server.app.services.pricing_service import (
                update_prices_from_openrouter,
            )

            await update_prices_from_openrouter()

            # Update last run timestamp
            await self._update_last_run()

            logger.info("Refresco de modelos completado")
        except Exception:
            # `exception` y no `error`: el traceback es lo unico que dice DONDE fallo, y con
            # `print(e)` se perdia entero. Esta tarea corre sola de madrugada, asi que nadie
            # va a estar mirando para reproducirlo.
            logger.exception("Fallo el refresco programado de modelos")

    def _add_job(self, hour: int, minute: int):
        """Add or replace the refresh job with given schedule."""
        # Remove existing job if present
        if self._scheduler.get_job(self._job_id):
            self._scheduler.remove_job(self._job_id)

        # Add new job with cron trigger
        trigger = CronTrigger(hour=hour, minute=minute)
        self._scheduler.add_job(
            self._run_refresh_task,
            trigger=trigger,
            id=self._job_id,
            name="Daily Model Cache Refresh",
            replace_existing=True,
        )
        logger.info("Tarea programada cada dia a las %02d:%02d", hour, minute)

    def _run_refresh_task(self):
        """Wrapper to run async task from sync scheduler callback."""
        asyncio.create_task(self._refresh_task())

    async def start(self):
        """
        Inicia el motor del planificador si está habilitado en la configuración.

        Returns:
            bool: True si el servicio se inició correctamente.
        """
        config = await self._get_config()

        if not config.enabled:
            logger.info("El planificador esta deshabilitado en la configuracion: no arranca")
            return False

        if self._scheduler.running:
            logger.info("El planificador ya estaba en marcha")
            return True

        self._add_job(config.refresh_hour, config.refresh_minute)
        self._scheduler.start()
        logger.info(
            "Planificador arrancado; proximo refresco a las %02d:%02d",
            config.refresh_hour,
            config.refresh_minute,
        )
        return True

    async def stop(self):
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Planificador detenido")

    async def update_schedule(self, enabled: bool, hour: int, minute: int):
        """Update scheduler configuration and reschedule if needed."""
        async with AsyncSession(server_engine) as session:
            config = await session.get(SchedulerConfig, 1)
            if not config:
                config = SchedulerConfig(id=1)

            config.enabled = enabled
            config.refresh_hour = hour
            config.refresh_minute = minute
            config.updated_at = datetime.utcnow()

            session.add(config)
            await session.commit()

        # Apply changes
        if enabled:
            if not self._scheduler.running:
                self._scheduler.start()
            self._add_job(hour, minute)
            logger.info("Horario actualizado a las %02d:%02d", hour, minute)
        else:
            if self._scheduler.running:
                if self._scheduler.get_job(self._job_id):
                    self._scheduler.remove_job(self._job_id)
            logger.info("Planificador deshabilitado")

    async def run_now(self):
        """Manually trigger a refresh immediately."""
        logger.info("Refresco lanzado a mano")
        await self._refresh_task()

    def is_running(self) -> bool:
        """Check if scheduler is currently running."""
        return self._scheduler.running if self._scheduler else False

    async def get_status(self) -> dict:
        """Get current scheduler status."""
        config = await self._get_config()
        job = self._scheduler.get_job(self._job_id) if self._scheduler else None

        return {
            "enabled": config.enabled,
            "running": self.is_running(),
            "refresh_hour": config.refresh_hour,
            "refresh_minute": config.refresh_minute,
            "last_run": config.last_run.isoformat() if config.last_run else None,
            "next_run": job.next_run_time.isoformat()
            if job and job.next_run_time
            else None,
        }


# Global singleton instance
scheduler_service = ModelRefreshScheduler()
