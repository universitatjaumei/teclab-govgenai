"""De `funcion@versión` a algo ejecutable, y nunca a nada en silencio (FUN.3).

Deploy: edge.

El nodo de extracción no sabe —ni tiene que saber— de dónde sale el código de una función. Le
pide a este resolutor «lo ejecutable» de una referencia y recibe un objeto que sabe describirse:
qué darle al pipeline y qué anotar en el manifiesto. En FUN.5 este mismo resolutor gana el origen
empaquetado, que devuelve un *callable* en vez de código, **sin tocar el nodo**.

**Falla en alto, siempre.** Una función retirada, una versión que no existe o una suspendida
hacen fallar el bloque con un mensaje que nombra la función y, si está suspendida, el motivo. La
alternativa —devolver vacío— es la lección de los perfiles sin configurar: parecía funcionar y
producía informes sin datos que nadie relacionaba con la causa.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

#: Los estados en los que una versión **no** se ejecuta, con lo que hay que decir de cada uno.
#: `no_instalada` es de FUN.5 y ya está aquí porque el mensaje es el mismo problema.
_POR_QUE_NO: dict[str, str] = {
    "draft": "está en borrador: todavía no se ha registrado",
    "suspendida": "está suspendida",
    "retirada": "está retirada por su autor",
    "no_instalada": "es de un paquete que ya no está instalado en este despliegue",
}


class FuncionNoEjecutable(RuntimeError):
    """La referencia de un bloque no lleva a nada que se pueda ejecutar.

    Se levanta y no se traga: el bloque tiene que fallar en alto, con el nombre de la función y
    el motivo, para que quien mire el informe sepa por qué dejó de funcionar.
    """


@dataclass(frozen=True)
class FuncionEjecutable:
    """Lo que hace falta para ejecutar una versión y para poder decir qué se ejecutó."""

    funcion_id: uuid.UUID
    nombre: str
    version: int
    origen: str
    code: str | None
    code_sha256: str
    contrato_entrada: dict[str, Any]
    #: Sólo en origen `paquete` (FUN.5): la versión semver realmente instalada, que puede no ser
    #: la anclada. En autoservicio es `None` porque el anclaje es exacto.
    version_paquete: str | None = None
    #: Sólo en origen `paquete`: por dónde llegar al `run` instalado. El callable no cabe en la
    #: base de datos, así que lo que se guarda es su dirección y el proceso lo resuelve.
    entry_point: str | None = None

    def como_opciones_del_pipeline(self) -> dict[str, Any]:
        """Lo que el pipeline de script espera. **El protocolo no cambia.**

        `approved=True` sigue ahí porque el pipeline lo exige, y ahora significa lo que de verdad
        ocurrió: la versión está **registrada**, o sea auditada sin hallazgos críticos y probada
        en el sandbox. Eso es la puerta del nivel 2 de la Instrucció; la aprobación humana previa
        ya no lo es.
        """
        return {"code": self.code or "", "approved": True}

    def para_el_manifiesto(self) -> dict[str, Any]:
        """Lo que el `RunManifest` anota. Hasta FUN.3 no anotaba nada de esto: el código iba
        incrustado en la plantilla y no tenía identidad, así que «qué corrió» no se podía
        responder."""
        anotacion: dict[str, Any] = {
            "funcion_id": str(self.funcion_id),
            "nombre": self.nombre,
            "version": self.version,
            "origen": self.origen,
            "code_sha256": self.code_sha256,
        }
        if self.version_paquete is not None:
            anotacion["version_paquete"] = self.version_paquete
        return anotacion


class ResolvedorDeFuncion:
    """Resuelve una referencia del catálogo. Un solo método, para que el nodo no sepa de orígenes."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def resolver(self, funcion_id: uuid.UUID, version: int) -> FuncionEjecutable:
        from sqlalchemy import select

        from server.app.modules.redaccion.database.models import (
            HubFuncion,
            HubFuncionVersion,
        )

        funcion = await self._session.get(HubFuncion, funcion_id)
        if funcion is None:
            raise FuncionNoEjecutable(
                f"la función {funcion_id} no está en el catálogo: la plantilla referencia algo "
                "que no existe"
            )

        fila = (
            await self._session.execute(
                select(HubFuncionVersion)
                .where(HubFuncionVersion.funcion_id == funcion_id)
                .where(HubFuncionVersion.version == version)
            )
        ).scalar_one_or_none()

        if fila is None:
            raise FuncionNoEjecutable(
                f"la función «{funcion.nombre}» no tiene versión {version}: la plantilla está "
                "anclada a una versión que no existe"
            )

        if funcion.origen == "paquete":
            # FUN.5 — **el anclaje de un paquete es por mayor, no exacto.** Es lo que compra el
            # semver: instalar 1.3.0 no puede romper las plantillas ancladas a la versión del
            # catálogo que trajo 1.2.0. Lo que sí rompe un mayor distinto, porque el contrato
            # puede haber cambiado, y ejecutarlo en silencio cambiaría el significado de un
            # informe sin decírselo a nadie.
            return await self._resolver_paquete(funcion, fila)

        if funcion.origen == "externa":
            # AUT.3 — **la puerta que faltaba cerrar.** Todo lo que no era `paquete` caía en la
            # rama de abajo y salía como código ejecutable en el sandbox, así que un cuaderno
            # registrado «para no ejecutarlo» se ejecutaba en cuanto una plantilla lo anclaba.
            # La revisión de la PR #189 lo encontró; el `409` del endpoint de ejecución no
            # bastaba, porque ésta es otra entrada.
            raise FuncionNoEjecutable(
                f"«{funcion.nombre}» es de origen externo: se registra en la plataforma y se "
                f"ejecuta fuera "
                f"({fila.entorno_ejecucion or 'donde la tenga su autora'}), con las "
                f"credenciales de quien la usa. Una plantilla no puede anclarla."
            )

        if fila.estado != "registrada":
            motivo = _POR_QUE_NO.get(fila.estado, f"está en estado «{fila.estado}»")
            detalle = ""
            if fila.estado == "suspendida" and fila.motivo_suspension:
                detalle = f" — motivo: {fila.motivo_suspension}"
            raise FuncionNoEjecutable(
                f"la versión {version} de «{funcion.nombre}» no se puede ejecutar: "
                f"{motivo}{detalle}"
            )

        return FuncionEjecutable(
            funcion_id=funcion.id,
            nombre=funcion.nombre,
            version=fila.version,
            origen=funcion.origen,
            code=fila.code,
            code_sha256=fila.code_sha256,
            contrato_entrada=dict(fila.contrato_entrada or {}),
            version_paquete=fila.version_paquete,
        )

    async def _resolver_paquete(self, funcion: Any, anclada: Any) -> FuncionEjecutable:
        """La versión instalada **compatible** con la anclada, o un fallo que nombra los dos.

        Se busca por mayor y no por ordinal: el ordinal del catálogo es interno y lo que el
        paquete promete es su semver. Y el `FuncionEjecutable` que sale lleva la versión
        **instalada exacta** con su hash, no la anclada: el `RunManifest` no puede decir que
        corrió algo que no corrió.
        """
        from sqlalchemy import select

        from server.app.modules.redaccion.database.models import HubFuncionVersion
        from server.app.modules.redaccion.funciones_paquete import (
            PaqueteIncoherente,
            mayor_de,
        )

        try:
            mayor_anclado = mayor_de(anclada.version_paquete or "")
        except PaqueteIncoherente as exc:
            raise FuncionNoEjecutable(
                f"la versión {anclada.version} de «{funcion.nombre}» no dice a qué versión del "
                f"paquete está anclada: {exc}"
            ) from exc

        instaladas = [
            v
            for v in (
                await self._session.execute(
                    select(HubFuncionVersion)
                    .where(HubFuncionVersion.funcion_id == funcion.id)
                    .where(HubFuncionVersion.estado == "registrada")
                    # DET.1: dos versiones pueden compartir instante, así que se desempata.
                    .order_by(HubFuncionVersion.version.desc(), HubFuncionVersion.id)
                )
            ).scalars().all()
        ]

        if not instaladas:
            raise FuncionNoEjecutable(
                f"«{funcion.nombre}» no tiene ninguna versión instalada: su paquete no está "
                f"presente en este despliegue, así que todas sus versiones están "
                f"«no_instalada». Instálalo o retira la referencia de la plantilla."
            )

        compatibles = [
            v for v in instaladas if mayor_de(v.version_paquete or "0.0.0") == mayor_anclado
        ]
        if not compatibles:
            mayores = sorted({mayor_de(v.version_paquete or "0.0.0") for v in instaladas})
            raise FuncionNoEjecutable(
                f"«{funcion.nombre}» está anclada al mayor {mayor_anclado} y lo instalado es "
                f"el mayor {', '.join(str(m) for m in mayores)}. Un mayor distinto puede haber "
                f"cambiado el contrato, así que no se ejecuta: o se instala una versión "
                f"{mayor_anclado}.x, o se reancla la plantilla a la nueva tras revisarla."
            )

        elegida = compatibles[0]
        return FuncionEjecutable(
            funcion_id=funcion.id,
            nombre=funcion.nombre,
            version=elegida.version,
            origen=funcion.origen,
            code=None,
            code_sha256=elegida.code_sha256,
            contrato_entrada=dict(elegida.contrato_entrada or {}),
            version_paquete=elegida.version_paquete,
            entry_point=funcion.entry_point,
        )
