"""El despliegue: sin claves de larga vida, con etiqueta identificable y con vuelta atrás (D.5-VM).

Los tres invariantes que este workflow tiene que cumplir, y que se rompen sin ruido:

- **Ninguna credencial permanente.** Una clave JSON de cuenta de servicio en los secretos del
  repositorio es una credencial que nadie rota y que se lleva quien lea los secretos una vez.
  Se autentica por federación, y aquí se comprueba que no ha vuelto una clave.
- **La etiqueta es el SHA, nunca `latest`.** Con `latest` no se puede responder «qué está
  corriendo» ni «vuelve a lo de antes», que son las dos preguntas de un incidente.
- **Las migraciones van antes de cambiar la imagen.** El orden es el invariante, no la
  existencia del paso: si se cuelan después, un fallo de Alembic deja la imagen nueva sirviendo
  contra un esquema viejo.

Y una cuarta que es del aprovisionamiento: el proveedor de identidad tiene que estar **acotado
al repositorio**. Sin `--attribute-condition`, acepta tokens de cualquier repositorio de GitHub
y cualquiera podría suplantar a la cuenta de despliegue. Es el error clásico de esta
configuración.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
WORKFLOW = RAIZ / ".github" / "workflows" / "deploy.yml"
PROVISION = RAIZ / "scripts" / "gcp_provision_cicd.sh"
COMPOSE = RAIZ / "deploy" / "vm" / "docker-compose.vm.yml"


def _texto(ruta: Path) -> str:
    assert ruta.is_file(), f"Falta {ruta.relative_to(RAIZ).as_posix()}"
    return ruta.read_text(encoding="utf-8")


def _workflow() -> dict:
    return yaml.safe_load(_texto(WORKFLOW))


def _pasos() -> list[dict]:
    datos = _workflow()
    trabajos = datos["jobs"]
    assert len(trabajos) == 1, "Se espera un solo trabajo de despliegue."
    return next(iter(trabajos.values()))["steps"]


def _nombres_de_paso() -> list[str]:
    return [p.get("name", p.get("uses", "")) for p in _pasos()]


def test_el_workflow_es_yaml_valido_y_tiene_un_solo_trabajo() -> None:
    datos = _workflow()
    assert "jobs" in datos
    assert datos.get("concurrency", {}).get("cancel-in-progress") is False, (
        "Un despliegue a medias no se cancela: dejaría la máquina en un estado intermedio."
    )


# ---------------------------------------------------------------------------
# Sin claves de larga vida
# ---------------------------------------------------------------------------


def test_se_autentica_por_federacion_y_no_con_una_clave() -> None:
    texto = _texto(WORKFLOW)
    assert "workload_identity_provider" in texto, "Falta la federación de identidad."
    assert "credentials_json" not in texto, (
        "`credentials_json` es una clave de cuenta de servicio: una credencial permanente en "
        "los secretos del repositorio. Se autentica por federación."
    )
    assert not re.search(r"secrets\.GCP_[A-Z_]*KEY", texto), (
        "No debe haber ninguna clave de GCP en los secretos del repositorio."
    )

    datos = _workflow()
    assert datos["permissions"]["id-token"] == "write", (
        "La federación exige `id-token: write`; sin ello el canje de token falla."
    )


def test_los_identificadores_van_en_vars_y_no_en_secrets() -> None:
    """Un proyecto o una región no son secretos, y tratarlos como tales esconde qué se
    despliega a dónde sin proteger nada."""
    texto = _texto(WORKFLOW)
    for identificador in ("GCP_PROJECT_ID", "GCP_REGION", "GCP_WIF_PROVIDER", "GCP_DEPLOY_SA"):
        assert f"vars.{identificador}" in texto, f"{identificador} debería venir de `vars`"
        assert f"secrets.{identificador}" not in texto


# ---------------------------------------------------------------------------
# La etiqueta
# ---------------------------------------------------------------------------


def test_la_imagen_se_etiqueta_con_el_sha_y_nunca_con_latest() -> None:
    texto = _texto(WORKFLOW)
    assert "GITHUB_SHA" in texto, "La etiqueta tiene que salir del SHA del commit."
    etiquetas_latest = re.findall(r":latest\b", texto)
    assert not etiquetas_latest, (
        "`latest` no sirve para saber qué corre ni para volver atrás: usa el SHA."
    )


def test_se_puede_desplegar_una_etiqueta_concreta_para_volver_atras() -> None:
    datos = _workflow()
    # `on:` lo parsea YAML 1.1 como el booleano True, no como la cadena "on". Es la trampa
    # clásica de leer un workflow de GitHub con `yaml.safe_load`, y cayó el primer intento.
    disparadores = datos.get("on", datos.get(True))
    assert disparadores, "No se han podido leer los disparadores del workflow."
    entradas = disparadores["workflow_dispatch"]["inputs"]
    assert "etiqueta" in entradas, (
        "Tiene que poder lanzarse a mano con una etiqueta: es el camino de vuelta manual."
    )


# ---------------------------------------------------------------------------
# El orden, que es el invariante
# ---------------------------------------------------------------------------


def test_las_migraciones_van_antes_de_cambiar_la_imagen() -> None:
    nombres = _nombres_de_paso()
    indice_migracion = next(
        (i for i, n in enumerate(nombres) if "Migraciones" in n), None
    )
    indice_despliegue = next(
        (i for i, n in enumerate(nombres) if n.strip() == "Desplegar"), None
    )
    assert indice_migracion is not None, f"No hay paso de migraciones: {nombres}"
    assert indice_despliegue is not None, f"No hay paso de despliegue: {nombres}"
    assert indice_migracion < indice_despliegue, (
        "Las migraciones tienen que ir ANTES de cambiar la imagen. Si van después, un fallo "
        "de Alembic deja la imagen nueva sirviendo contra un esquema viejo."
    )


def test_el_cliente_de_la_api_se_genera_antes_de_construir_las_imagenes() -> None:
    """`frontend/src/shared/api/generated/` está en .gitignore: es código generado por Orval
    desde `openapi.json` y no viaja en el repositorio. Sin generarlo, `docker build ./frontend`
    falla con veinte «Cannot find module '@/shared/api/generated/…'» — que es exactamente
    dónde murió el primer despliegue.
    """
    nombres = _nombres_de_paso()
    indice_cliente = next(
        (i for i, n in enumerate(nombres) if "cliente de la API" in n), None
    )
    indice_imagenes = next(
        (i for i, n in enumerate(nombres) if "imágenes" in n or "imagenes" in n), None
    )
    assert indice_cliente is not None, (
        f"Falta el paso que genera el cliente de la API: {nombres}"
    )
    assert indice_imagenes is not None, f"Falta el paso que construye las imágenes: {nombres}"
    assert indice_cliente < indice_imagenes, (
        "El cliente se genera ANTES de construir la imagen del frontend."
    )

    texto = _texto(WORKFLOW)
    assert "export_openapi.py" in texto, (
        "El cliente sale de `openapi.json`, que exporta el backend: sin ese paso, Orval "
        "generaría contra un contrato viejo o ninguno."
    )
    assert "generate:api" in texto


def test_la_configuracion_anterior_se_guarda_antes_de_desplegar() -> None:
    nombres = _nombres_de_paso()
    indice_anterior = next((i for i, n in enumerate(nombres) if "anterior" in n), None)
    indice_despliegue = next((i for i, n in enumerate(nombres) if n.strip() == "Desplegar"), None)
    assert indice_anterior is not None, "No se guarda la configuración anterior."
    assert indice_anterior < indice_despliegue, (
        "Se guarda antes de desplegar, o no hay a dónde volver."
    )


def test_la_vuelta_atras_restaura_el_fichero_entero_y_sin_variables_remotas() -> None:
    """Dos fallos reales del sexto despliegue, los dos en la vuelta atrás.

    (1) Rehacía con `sed` sólo la línea de la imagen de la aplicación, dejando frontend y
    sandbox en la versión nueva: una vuelta atrás a medias es un estado que nadie ha probado.
    (2) Mandaba `${ANTERIOR}` **escapado**, así que lo expandía el intérprete de la máquina
    —donde no existe— y el `sed` escribía `GOVGENAI_IMAGE=` vacío. Desde ahí compose no podía
    interpolar ni para levantar ni para bajar, y como `ExecStop` es el mismo compose, la pila
    se quedó a medias.
    """
    texto = _texto(WORKFLOW)
    assert ".env.despliegue.anterior" in texto, (
        "La vuelta atrás restaura el fichero de configuración entero."
    )
    activas = [
        linea for linea in texto.splitlines()
        if "sed -i" in linea and "GOVGENAI_IMAGE" in linea and not linea.strip().startswith("#")
    ]
    assert not activas, f"La vuelta atrás no debe reescribir la imagen con sed: {activas}"
    assert "\\${" not in texto, (
        "Una variable escapada la expande el intérprete remoto, donde no existe. Si el valor "
        "tiene que viajar, se expande en el runner."
    )


def test_la_comprobacion_de_docs_mide_la_api_y_no_el_frontend() -> None:
    """El frontend es una SPA con catch-all: `https://host/docs` devuelve `index.html` con 200
    para cualquier ruta. La primera versión miraba ahí, leyó ese 200 como «documentación
    abierta» y **revirtió un despliegue que funcionaba**. Medía el frontend creyendo medir la
    API.
    """
    texto = _texto(WORKFLOW)
    lineas = [
        linea for linea in texto.splitlines()
        if 'HOST/docs' in linea and not linea.strip().startswith("#")
    ]
    assert not lineas, (
        f"No se puede comprobar el /docs de la raíz: lo sirve el frontend. {lineas}"
    )
    assert "/api/v1/openapi.json" in texto, (
        "La comprobación externa va bajo el prefijo de la API."
    )
    assert "docker exec govgenai_app" in texto, "La comprobación autoritativa es dentro del contenedor, que es donde actúa SEC.7."
    assert "localhost:8000/docs" in texto, "La comprobación autoritativa es dentro del contenedor, que es donde actúa SEC.7."


def test_hay_comprobacion_posterior_y_reversion() -> None:
    texto = _texto(WORKFLOW)
    assert "/health" in texto, "Falta la comprobación de que sirve."
    assert "/docs" in texto, "Falta comprobar que /docs está cerrado en producción (SEC.7)."
    assert "systemctl restart govgenai" in texto
    assert "Volviendo a la configuración anterior" in texto, (
        "Tiene que existir el camino de vuelta, y decirse en el log."
    )


def test_la_reversion_corre_aunque_el_despliegue_falle() -> None:
    """La red de seguridad tiene que estar puesta JUSTO cuando el despliegue se cae.

    Dos incidentes, la misma línea que faltaba. En GitHub Actions un paso fallido salta todo lo
    que viene detrás salvo lo marcado `if: always()`, así que sin él la reversión **no corre
    precisamente cuando hace falta**: si «Desplegar» muere, el servicio se queda caído en vez de
    volver a la imagen anterior.

    * **2026-09-01** — el disco se llenó, `docker compose up` murió, y no hubo reversión. Quedó
      anotado en `PROJECT_STATE.md` como «merece mirarse si ese paso debería correr con
      `if: always()`».
    * **2026-09-15** — no se miró. `uvicorn` salió del conjunto base al mover `browser-use` a un
      extra (DEP.1), el contenedor no arrancó, y producción estuvo caída media hora **con la
      reversión preparada en la máquina y sin ejecutar**.

    Y `continue-on-error` no vale: dice «si este paso falla, no tumbes el job», no «ejecútalo
    aunque uno anterior fallara». Es la tercera vez que esa confusión cuesta algo aquí.
    """
    import yaml

    flujo = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    pasos = next(iter(flujo["jobs"].values()))["steps"]
    comprobacion = [p for p in pasos if "Comprobar que sirve" in p.get("name", "")]
    assert len(comprobacion) == 1, (
        f"Se esperaba un único paso de comprobación y reversión, y hay {len(comprobacion)}."
    )
    assert comprobacion[0].get("if") == "always()", (
        "El paso «Comprobar que sirve, y volver atrás si no» necesita `if: always()`. Sin él se "
        "salta cuando «Desplegar» falla — o sea, cuando es su único momento útil — y el servicio "
        "se queda caído con la reversión preparada y sin ejecutar. Pasó el 2026-09-01 y otra vez "
        "el 2026-09-15."
    )


# ---------------------------------------------------------------------------
# Lo que el despliegue NO hace
# ---------------------------------------------------------------------------


def test_no_se_despliega_con_git_pull_en_la_maquina() -> None:
    texto = _texto(WORKFLOW)
    # Sólo líneas activas: el comentario de cabecera explica por qué NO se hace así.
    activas = [
        linea for linea in texto.splitlines()
        if "git pull" in linea and not linea.strip().startswith("#")
    ]
    assert not activas, (
        "Con `git pull` lo que corre depende del estado del disco de la máquina y no de un "
        f"artefacto identificable: {activas}"
    )


def test_el_despliegue_no_ejecuta_la_suite() -> None:
    texto = _texto(WORKFLOW)
    for orden in ("pytest", "npm test", "vitest"):
        activas = [
            linea for linea in texto.splitlines()
            if orden in linea and not linea.strip().startswith("#")
        ]
        assert not activas, (
            f"La suite corre en ci.yml sobre el mismo commit; repetirla aquí alarga el "
            f"despliegue sin añadir información: {activas}"
        )


# ---------------------------------------------------------------------------
# Las migraciones, en su servicio
# ---------------------------------------------------------------------------


def test_el_servicio_de_migracion_esta_bajo_perfil_y_no_usa_uv() -> None:
    datos = yaml.safe_load(_texto(COMPOSE))
    migrate = datos["services"]["migrate"]
    assert migrate.get("profiles") == ["migrate"], (
        "Bajo perfil, o `up -d` ejecutaría las migraciones dentro del arranque."
    )
    assert migrate["command"] == ["alembic", "upgrade", "head"], (
        "La imagen de runtime no lleva `uv`: tiene el venv en el PATH. Con `uv run` el "
        "despliegue fallaría con «executable file not found»."
    )
    assert migrate.get("restart") == "no", "Una migración no se reintenta sola."


# ---------------------------------------------------------------------------
# El aprovisionamiento
# ---------------------------------------------------------------------------


def test_el_proveedor_de_identidad_esta_acotado_al_repositorio() -> None:
    texto = _texto(PROVISION)
    assert "--attribute-condition" in texto, (
        "Sin condición de atributo, el proveedor acepta tokens de CUALQUIER repositorio de "
        "GitHub y cualquiera podría suplantar a la cuenta de despliegue."
    )
    assert "assertion.repository==" in texto
    assert "attribute.repository/" in texto, (
        "El binding tiene que ser sobre `attribute.repository/<repo>`, no sobre el pool entero."
    )


def test_el_aprovisionamiento_exige_el_repositorio() -> None:
    texto = _texto(PROVISION)
    assert 'falta --repo' in texto, (
        "El repositorio no puede tener valor por defecto: es lo que acota quién despliega."
    )


def test_la_cuenta_de_despliegue_puede_actuar_como_la_de_la_maquina() -> None:
    """Sin `actAs` sobre la cuenta de la VM, `gcloud compute scp` y `ssh` fallan con
    «User does not have iam.serviceAccounts.actAs permission on the instance's service
    account» — y el mensaje no dice sobre qué cuenta falta el permiso. El segundo despliegue
    real murió aquí.

    Y se concede **sobre esa cuenta**, no a nivel de proyecto: `serviceAccountUser` en el
    proyecto permitiría suplantar a cualquier cuenta de servicio.
    """
    texto = _texto(PROVISION)
    assert "roles/iam.serviceAccountUser" in texto, (
        "Falta el permiso que permite entrar en la máquina."
    )
    assert "VM_SA" in texto, "El permiso tiene que concederse sobre la cuenta de la VM."
    proyecto_entero = [
        linea for linea in texto.splitlines()
        if "projects add-iam-policy-binding" in linea and "serviceAccountUser" in linea
    ]
    assert not proyecto_entero, (
        f"`serviceAccountUser` no se concede a nivel de proyecto: {proyecto_entero}"
    )


def test_refrescar_los_metadatos_usa_un_rol_propio_y_no_el_de_administrador() -> None:
    """`compute.viewer` es de sólo lectura, así que el paso que refresca el guion de arranque
    murió con «Required 'compute.instances.setMetadata' permission». La salida cómoda era
    `roles/compute.instanceAdmin.v1`, que trae de regalo apagar y **borrar** la máquina: una
    cuenta que despliega no necesita poder destruir el destino.
    """
    texto = _texto(PROVISION)
    assert "compute.instances.setMetadata" in texto, (
        "Falta el permiso para refrescar el guion de arranque."
    )
    # Sólo líneas activas: el comentario que justifica la decisión también nombra el rol
    # que se descarta.
    admin = [
        linea for linea in texto.splitlines()
        if "roles/compute.instanceAdmin" in linea and not linea.strip().startswith("#")
    ]
    assert not admin, (
        f"No se concede administración de instancias: basta un rol propio. {admin}"
    )
    assert "--permissions=" in texto, "El rol propio se crea desde el guion, para que el aprovisionamiento sea repetible."
    assert "--stage=GA" in texto, "El rol propio se crea desde el guion, para que el aprovisionamiento sea repetible."


def test_la_cuenta_de_despliegue_no_es_de_editor_ni_de_propietario() -> None:
    texto = _texto(PROVISION)
    assert "roles/editor" not in texto
    assert "roles/owner" not in texto
    for rol in ("roles/artifactregistry.writer", "roles/iap.tunnelResourceAccessor"):
        assert rol in texto, f"Falta el rol mínimo {rol}"


# ---------------------------------------------------------------------------
# El disco de la máquina (incidente del 2026-09-01)
# ---------------------------------------------------------------------------


def test_el_despliegue_retira_las_imagenes_que_ya_no_usa_ningun_contenedor() -> None:
    """Sin esto el disco de la VM se llena y el servicio se cae, y no en el despliegue que lo
    llena: en el siguiente.

    Pasó el 2026-09-01. Diez despliegues habían dejado **30 imágenes y 25,2 GB** en un disco de
    30 GB —la de `app` pesa 2,26 GB y cada despliegue publica tres—, y el `docker compose up`
    murió con `no space left on device` al no poder crear el socket del proxy de Cloud SQL. El
    síntoma no señalaba al disco por ningún lado: la unidad decía «dependency failed to start:
    container govgenai_sql_proxy is unhealthy».

    Y lo que lo hace peor: el paso de comprobación con vuelta atrás **se salta** cuando el paso
    de desplegar falla, así que no hubo reversión — el servicio se quedó caído.
    """
    texto = _texto(WORKFLOW)
    activas = [
        linea for linea in texto.splitlines()
        if "image prune" in linea and not linea.strip().startswith("#")
    ]
    assert activas, (
        "Falta un `docker image prune` en el despliegue. Diez despliegues sin limpiar llenaron "
        "un disco de 30 GB y tumbaron el servicio."
    )
    # `-a` (o `--all`) es lo que retira las imágenes de despliegues anteriores: sin él sólo se
    # van las huérfanas sin etiqueta, que no son las que ocupan.
    assert any("-a" in linea or "--all" in linea for linea in activas), (
        f"El prune tiene que ser `-a`: sin eso las imágenes etiquetadas de despliegues "
        f"anteriores se quedan, y son justo las que llenan el disco. {activas}"
    )
    # ANTES de que la máquina descargue las imágenes nuevas, y la posición es el diseño.
    #
    # En ese punto los contenedores siguen apuntando a la generación actual, y `prune -a`
    # conserva exactamente lo que algún contenedor referencia: se conserva la actual, se libera
    # todo lo anterior, y la descarga que viene tiene sitio garantizado. Tras el reinicio la
    # generación anterior se queda en local sin contenedor, así que una vuelta atrás no tiene
    # que volver a bajar 2,26 GB. Estado estacionario: dos generaciones.
    #
    # La primera versión lo puso después de desplegar. Funcionaba, pero dejaba la reversión
    # dependiendo de una descarga y no garantizaba sitio para la descarga de ida — que es
    # justamente lo que falló.
    assert texto.index("image prune") < texto.index("- name: Migraciones"), (
        "El prune va ANTES de que la máquina baje las imágenes nuevas (las migraciones son el "
        "primer paso que tira de la imagen de `app`). Después de desplegar también libera, pero "
        "no garantiza sitio para la descarga de ida y deja la vuelta atrás dependiendo de otra."
    )


def test_el_dominio_institucional_llega_por_configuracion_y_no_a_mano() -> None:
    """El fichero de entorno se REGENERA en cada despliegue, así que editarlo a mano no sirve.

    El 2026-09-01 se añadió `GOVGENAI_HOST_INSTITUCIONAL` a mano en la VM y el primer despliegue
    la borró: el paso «Escribir la configuración del despliegue» sobrescribe el fichero entero
    desde `vars`. No causó daño —el guion del certificado trata la variable vacía como «no hay
    dominio» y retira el sitio— pero el dominio no se servía y nada lo decía.
    """
    texto = _texto(WORKFLOW)
    assert "GOVGENAI_HOST_INSTITUCIONAL" in texto, (
        "El dominio institucional tiene que salir de `vars` como el resto de identificadores: "
        "el fichero de entorno de la VM se sobrescribe en cada despliegue."
    )
    activas = [
        linea for linea in texto.splitlines()
        if "GOVGENAI_HOST_INSTITUCIONAL" in linea and not linea.strip().startswith("#")
    ]
    assert any("vars." in linea for linea in activas), (
        f"Y de `vars`, no de `secrets`: es un nombre de host, no una credencial. {activas}"
    )


def test_un_commit_solo_de_documentacion_no_redespliega_produccion() -> None:
    """Cambiar un `.md` no puede reiniciar el servicio, y hoy lo hacía.

    Medido el 2026-09-01: el commit `16b5f61` tocaba **sólo** `planificacion/PROJECT_STATE.md`
    y disparó un despliegue completo que paró y levantó la pila. Consecuencias, las dos malas:

    - **Producción se reinicia sin motivo.** Cada reinicio deja el servicio 60-90 s sin
      responder, y ese día hubo cuatro.
    - **La vigilancia se vuelve ruido.** La alerta de salud dispara en cada reinicio, así que
      llegaban avisos «sin que se haya hecho ningún despliegue» —los había, sólo que de
      documentación—. Con avisos falsos de por medio se perdió uno real: el del disco al 85%,
      que había avisado cuatro horas antes de la caída.

    El filtro es por lo que NO se despliega, no por lo que sí: si mañana aparece un directorio
    de código nuevo, lo peor que pasa es que se despliegue, que es el lado seguro del error.
    """
    d = _workflow()
    # `on` es palabra reservada en YAML 1.1: PyYAML la lee como True.
    disparador = d.get("on") or d.get(True)
    assert disparador, "El workflow tiene que declarar su disparador."
    push = disparador.get("push") or {}
    ignoradas = push.get("paths-ignore") or []
    assert ignoradas, (
        "Falta `paths-ignore` en el disparador del despliegue: un commit de documentación "
        "reinicia producción y dispara la alerta de salud."
    )
    for esperada in ("docs/**", "planificacion/**", "**.md"):
        assert esperada in ignoradas, (
            f"{esperada} debería estar en paths-ignore. Actual: {ignoradas}"
        )
    # Y lo que NO puede estar: el código, el compose, los guiones y el propio workflow.
    for prohibida in ("server/**", "frontend/**", "deploy/**", "scripts/**",
                      ".github/workflows/**"):
        assert prohibida not in ignoradas, (
            f"{prohibida} NO puede ignorarse: es lo que se despliega. Actual: {ignoradas}"
        )
