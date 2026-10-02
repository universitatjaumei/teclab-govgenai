"""Módulos de la plataforma y quién puede entrar en cada uno (INF.7).

Deploy: cloud

Antes de esto **no había control de acceso por función**: `App.tsx` metía todas las rutas bajo
un `PrivateRoute` que solo comprobaba que hubiera sesión, no existía un solo `role ===` en la
capa de navegación, y los routers de `redaccion` usaban `get_current_user` a secas. Mientras la
aplicación la usaban administradores eso era una asimetría teórica; con el módulo de informes
abierto a toda la organización —el colectivo objetivo es «todo el que necesita hacer
informes»— deja de serlo: cualquier trabajador con cuenta podía listar y editar los chatbots
institucionales y la configuración de LLM.

**Por módulos concedidos, no por rol nuevo** (decisión del usuario, 2026-08-20). Un rol
`redactor` es más barato hoy y explota en cuanto alguien necesite informes y curación pero no
chatbots. Y el rol `informer` que ya existe no sirve: su contrato es «supervisa y valida
respuestas de la IA», que es control de calidad de chatbots.

**El catálogo es dato, no código.** Vive en tabla, con `vigente`, igual que el vocabulario del
corpus y por el mismo motivo: si los módulos fueran un `Enum` de Python o un `CheckConstraint`,
añadir uno exigiría una migración y un despliegue. Las constantes de abajo son **semillas** del
catálogo, no su definición: el código que decide pregunta a la tabla.

**El superadmin no necesita concesión.** Es el rol de la plataforma, y hacerlo depender de una
fila deja una instalación recién creada con un superadmin encerrado fuera de todo — el
`bootstrap` crea la cuenta, no sus permisos. Para cualquier otro rol, sin fila no hay acceso.
"""
from __future__ import annotations

#: Los módulos que existen al introducir el sistema. Semilla del catálogo, no su definición.
MODULOS_INICIALES: tuple[tuple[str, str], ...] = (
    ("chatbots", "Chatbots y asistentes"),
    ("curacion", "Curación de contenido"),
    ("informes", "Informes"),
    # USR.9 — separado de `plataforma` a propósito: administrar a las personas de tu
    # organización no es administrar la plataforma (modelos de LLM, organizaciones, tokens,
    # módulos), y meterlo ahí obligaba a dar todo eso para poder dar lo primero.
    ("personas", "Personas de la organización"),
    # REG.6 — el registro de usos de IA que declaran las herramientas de fuera. Módulo propio y
    # no dentro de `plataforma` por el mismo criterio que `personas`: es dato **operacional** de
    # la organización (`Deploy: edge`) y aquélla es configuración de la plataforma
    # (`Deploy: cloud`). Meterlo ahí obligaría a dar los modelos de LLM, las organizaciones y los
    # tokens para poder dar el registro.
    ("registro", "Registro de actividad IA"),
    # UTL (#190, #191) — operaciones sueltas sobre un fichero que hoy se hacen en webs que no
    # aseguran el RGPD: unir o partir un PDF, anonimizar un listado. Módulo propio y no dentro
    # de `informes`, porque no son informes: las necesita cualquiera que trabaje con documentos.
    ("utilidades", "Utilidades"),
    # #172 — publicar agentes de unidad. Usarlos no lo exige: el catálogo se le ofrece a su
    # colectivo, tenga o no el módulo. Lo que se concede es publicar.
    ("agentes", "Agentes de unidad"),
    ("plataforma", "Administración de la plataforma"),
)

#: Rol que entra en todos los módulos sin concesión explícita. Ver el docstring del módulo.
ROL_CON_ACCESO_TOTAL = "superadmin"
