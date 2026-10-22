"""Charts router — preview de gráficos sin persistencia (9R.5.7).

Deploy: edge
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from server.app.modules.redaccion.services.charts.chart_configuration import ChartConfiguration
from server.app.modules.redaccion.services.charts.deterministic_chart_service import DeterministicChartService
from server.app.api.deps import require_module

router = APIRouter(prefix="/redaccion/charts", tags=["redaccion-charts"],
    # INF.7 — el modulo se exige a nivel de router: asi no se puede olvidar en un
    # endpoint nuevo del mismo fichero, que es como se abrieron los agujeros que SEC.8.1
    # tuvo que cerrar uno a uno.
    dependencies=[Depends(require_module("informes"))],
)


class DeterministicPreviewRequest(BaseModel):
    config: ChartConfiguration
    rows: list[dict[str, Any]]


@router.post(
    "/preview/deterministic",
    summary="Preview determinista de gráfico",
    response_class=Response,
)
async def preview_deterministic(body: DeterministicPreviewRequest) -> Response:
    """Renderiza un gráfico determinista a partir de config + datos en línea.

    No persiste nada. Devuelve bytes PNG o SVG.
    """
    if not body.rows:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="rows cannot be empty")

    df = pd.DataFrame(body.rows)
    svc = DeterministicChartService()
    try:
        image_bytes = svc.render(df, body.config)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    media_type = "image/svg+xml" if body.config.output_format == "svg" else "image/png"
    return Response(content=image_bytes, media_type=media_type)
