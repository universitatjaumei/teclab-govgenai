"""Los datos de la consulta de un agente de unidad (#219).

Deploy: edge.

La unidad declara los datos esenciales que tiene que dar quien pregunta —en un agente de pliegos, el
tipo de contrato y el código CPV— y cada uno sirve a la vez para tres cosas: **preguntar** (la
pantalla pinta el formulario a partir de lo declarado), **seleccionar** y **componer el prompt**.

**Por qué seleccionar con ellos**: la selección compara la pregunta con el título y el resumen por
embeddings, que van bien con conceptos y mal con códigos —un embedding no distingue el CPV
79341000 del 79342000—. Para eso hace falta el valor, no la semejanza.

**El filtro es suave** (decisión del usuario, 2026-10-04): se excluye la ficha cuyo valor
**contradice** el indicado y se conserva la que no tiene el dato —la ley de contratos vale para
todos los pliegos—. Con `prefijo`, para códigos jerárquicos, casa en los dos sentidos: el CPV
79341000 casa con la ficha de 793 (un pliego tipo de toda la división) y 7934 con la de 79341000.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.app.modules.agentes.indice import normalizar_columna


class DatosNoValidos(ValueError):
    """Los datos de una consulta no casan con lo que declara el agente."""


@dataclass(frozen=True)
class Filtro:
    columna: str
    valor: str
    prefijo: bool


def clave(etiqueta: str) -> str:
    """La clave de un dato, que es la de su etiqueta como la de una columna: estable y legible."""
    return normalizar_columna(etiqueta)


def validar(declarados: list[dict[str, Any]], valores: dict[str, str]) -> list[tuple[dict[str, Any], str]]:
    """Los datos de la consulta, en el orden declarado. Falla con un mensaje que se puede leer."""
    conocidas = {d["clave"] for d in declarados}
    desconocidas = sorted(set(valores) - conocidas)
    if desconocidas:
        raise DatosNoValidos(f"este agente no pide {', '.join(desconocidas)}")
    pares: list[tuple[dict[str, Any], str]] = []
    for dato in declarados:
        valor = (valores.get(dato["clave"]) or "").strip()
        if not valor:
            if dato.get("obligatorio"):
                raise DatosNoValidos(f"falta «{dato['etiqueta']}»")
            continue
        if dato["tipo"] == "opciones" and valor not in dato.get("opciones", []):
            raise DatosNoValidos(f"«{valor}» no es una de las opciones de «{dato['etiqueta']}»")
        pares.append((dato, valor))
    return pares


def filtros(pares: list[tuple[dict[str, Any], str]]) -> list[Filtro]:
    """Sólo filtran los datos ligados a una columna del índice."""
    return [
        Filtro(columna=normalizar_columna(d["columna"]), valor=v.strip().lower(), prefijo=bool(d.get("prefijo")))
        for d, v in pares
        if d.get("columna")
    ]


def pasa(metadatos: dict[str, Any] | None, filtros_: list[Filtro]) -> bool:
    """Si la ficha se conserva: sólo cae la que tiene el dato y lo **contradice**."""
    if not filtros_:
        return True
    suyos = {normalizar_columna(k): str(v).strip().lower() for k, v in (metadatos or {}).items()}
    for f in filtros_:
        tiene = suyos.get(f.columna)
        if not tiene:
            continue
        casa = (tiene.startswith(f.valor) or f.valor.startswith(tiene)) if f.prefijo else tiene == f.valor
        if not casa:
            return False
    return True


def para_buscar(consulta: str, pares: list[tuple[dict[str, Any], str]]) -> str:
    """El texto que se embebe para seleccionar: la pregunta y los datos, que la describen mejor."""
    if not pares:
        return consulta
    return consulta + "\n" + "; ".join(f"{d['etiqueta']}: {v}" for d, v in pares)
