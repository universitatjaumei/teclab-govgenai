"""Tests 11.2 — docker-compose.prod.yml levanta TODO el stack con un solo comando.

Parsean los ficheros YAML/Dockerfile/nginx.conf; no levantan contenedores (la
verificación de arranque real se hace manualmente con `docker compose up`).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# Raíz del monorepo (AI_agents_hub/)
_ROOT = Path(__file__).parent.parent.parent.parent


def _load_compose(filename: str) -> dict:
    path = _ROOT / filename
    assert path.exists(), f"No existe {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _service_networks(svc: dict) -> list[str]:
    networks = svc.get("networks", [])
    return list(networks.keys()) if isinstance(networks, dict) else list(networks)


# ---------------------------------------------------------------------------
# 1. Servicio frontend: build multi-stage servido por nginx
# ---------------------------------------------------------------------------

def test_compose_prod_defines_frontend_service() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    services = compose.get("services", {})

    assert "frontend" in services, "Falta el servicio frontend en docker-compose.prod.yml"
    svc = services["frontend"]

    build = svc.get("build", {})
    assert build.get("context") == "./frontend", "frontend debe construirse desde ./frontend"
    assert build.get("dockerfile") == "Dockerfile"


def test_compose_prod_frontend_builds_with_relative_api_url() -> None:
    """VITE_API_URL vacío en build para que el frontend llame en same-origin (nginx proxy)."""
    compose = _load_compose("docker-compose.prod.yml")
    svc = compose["services"]["frontend"]
    build_args = svc.get("build", {}).get("args", {})

    assert "VITE_API_URL" in build_args
    assert build_args["VITE_API_URL"] == ""


def test_compose_prod_frontend_publica_el_80_contra_el_8080() -> None:
    """Fuera el 80, dentro el 8080 (issue #44).

    El contenedor dejó de escuchar en el 80 al pasar a `nginx-unprivileged`, porque dentro de
    un contenedor los puertos por debajo del 1024 exigen privilegios. Lo que se publica hacia
    fuera no cambia: quien abra el compose sigue entrando por el 80.
    """
    compose = _load_compose("docker-compose.prod.yml")
    svc = compose["services"]["frontend"]

    ports = [str(p) for p in svc.get("ports", [])]
    assert any(p.endswith("80:8080") for p in ports), \
        f"frontend debe publicar el 80 contra el 8080 del contenedor, encontrado: {ports}"


def test_compose_prod_frontend_has_healthcheck() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    svc = compose["services"]["frontend"]

    assert svc.get("healthcheck"), "frontend debe declarar healthcheck"


def test_compose_prod_frontend_depends_on_app_healthy() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    svc = compose["services"]["frontend"]

    depends_on = svc.get("depends_on", {})
    assert "app" in depends_on
    assert depends_on["app"].get("condition") == "service_healthy"


# ---------------------------------------------------------------------------
# 2. app espera a que las migraciones hayan terminado antes de arrancar
# ---------------------------------------------------------------------------

def test_compose_prod_app_waits_for_migrations_to_complete() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    app_svc = compose["services"]["app"]

    depends_on = app_svc.get("depends_on", {})
    assert "migrate" in depends_on, \
        "app debe depender de que 'migrate' complete con éxito (one-click real)"
    assert depends_on["migrate"].get("condition") == "service_completed_successfully"


# ---------------------------------------------------------------------------
# 3. Ollama es opcional: no arranca con `docker compose up` por defecto
# ---------------------------------------------------------------------------

def test_compose_prod_defines_optional_ollama_service() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    services = compose.get("services", {})

    assert "ollama" in services, "Falta el servicio ollama (opcional) en docker-compose.prod.yml"
    svc = services["ollama"]

    assert svc.get("profiles") == ["ollama"], \
        "ollama debe estar bajo el profile 'ollama' para no arrancar por defecto"
    assert svc.get("healthcheck"), "ollama debe declarar healthcheck"


def test_compose_prod_ollama_has_persistent_volume() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    svc = compose["services"]["ollama"]

    volumes = svc.get("volumes", [])
    assert any("ollama_data" in v for v in volumes), \
        "ollama debe persistir los modelos descargados en un volumen nombrado"

    top_level_volumes = compose.get("volumes", {})
    assert "ollama_data" in top_level_volumes


# ---------------------------------------------------------------------------
# 4. Persistencia: BD y almacenamiento en volúmenes nombrados
# ---------------------------------------------------------------------------

def test_compose_prod_has_named_volumes_for_db_and_storage() -> None:
    compose = _load_compose("docker-compose.prod.yml")
    volumes = compose.get("volumes", {})

    assert "postgres_data_prod" in volumes
    assert "s3_data_prod" in volumes


def test_compose_prod_has_no_orphaned_volume_declarations() -> None:
    """Todo volumen top-level declarado debe estar montado por al menos un servicio."""
    compose = _load_compose("docker-compose.prod.yml")
    top_level_volumes = set(compose.get("volumes", {}).keys())

    mounted: set[str] = set()
    for svc in compose.get("services", {}).values():
        for v in svc.get("volumes", []):
            name = v.split(":", 1)[0] if isinstance(v, str) else None
            if name:
                mounted.add(name)

    assert top_level_volumes <= mounted, \
        f"Volúmenes declarados pero no montados por ningún servicio: {top_level_volumes - mounted}"


# ---------------------------------------------------------------------------
# 5. Los servicios nuevos de este prompt (frontend, ollama) declaran healthcheck
# ---------------------------------------------------------------------------

def test_compose_prod_new_services_have_healthchecks() -> None:
    """frontend y ollama (introducidos en 11.2) declaran healthcheck propio."""
    compose = _load_compose("docker-compose.prod.yml")
    services = compose.get("services", {})

    for name in ("frontend", "ollama"):
        assert services[name].get("healthcheck"), f"El servicio '{name}' no declara healthcheck"


# ---------------------------------------------------------------------------
# 6. Dockerfile del frontend: build multi-stage node -> nginx
# ---------------------------------------------------------------------------

def test_frontend_dockerfile_is_multistage_node_to_nginx() -> None:
    dockerfile = _ROOT / "frontend" / "Dockerfile"
    assert dockerfile.exists(), f"No existe {dockerfile}"

    content = dockerfile.read_text(encoding="utf-8")
    from_lines = [line.strip() for line in content.splitlines() if line.strip().upper().startswith("FROM")]

    assert len(from_lines) >= 2, "El Dockerfile del frontend debe ser multi-stage (build + runtime)"
    assert any("node" in line.lower() for line in from_lines), \
        "Debe haber un stage de build basado en node"
    assert any("nginx" in line.lower() for line in from_lines), \
        "El stage final debe servir con nginx"
    assert "ARG VITE_API_URL" in content, \
        "El Dockerfile debe aceptar VITE_API_URL como build arg"
    assert "npm run build" in content or "npm ci" in content


def test_frontend_dockerfile_declares_healthcheck() -> None:
    dockerfile = _ROOT / "frontend" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "HEALTHCHECK" in content


# ---------------------------------------------------------------------------
# 7. nginx.conf: SPA routing + proxy same-origin del API (con soporte SSE)
# ---------------------------------------------------------------------------

def test_frontend_nginx_conf_proxies_api_to_backend() -> None:
    nginx_conf = _ROOT / "frontend" / "nginx.conf"
    assert nginx_conf.exists(), f"No existe {nginx_conf}"

    content = nginx_conf.read_text(encoding="utf-8")

    assert "location /api/" in content
    assert "proxy_pass http://app:8000" in content
    assert "proxy_buffering off" in content, \
        "El proxy debe desactivar el buffering para no romper el streaming SSE del chat"


def test_frontend_nginx_conf_serves_spa_fallback() -> None:
    nginx_conf = _ROOT / "frontend" / "nginx.conf"
    content = nginx_conf.read_text(encoding="utf-8")

    assert "try_files" in content, "El SPA routing requiere fallback a index.html"
    assert "index.html" in content, "El SPA routing requiere fallback a index.html"


# ---------------------------------------------------------------------------
# 8. dev y prod son proyectos Compose distintos (no comparten contenedores)
# ---------------------------------------------------------------------------

def test_root_dockerfile_grants_appuser_write_access_to_data_dir() -> None:
    """hub_themes_router.py crea data/themes (ruta relativa) al importarse.
    Regresión 11.2: appuser (no-root) no podía escribir bajo /app (propiedad
    de root), y el contenedor 'app' nunca superaba el import de main.py."""
    dockerfile = _ROOT / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "/app/data" in content
    assert "chown" in content
    # El chown debe ocurrir ANTES de cambiar a appuser.
    chown_idx = content.index("chown")
    user_idx = content.index("USER appuser")
    assert chown_idx < user_idx, "chown de /app/data debe preceder a USER appuser"


def test_dev_and_prod_compose_have_distinct_project_names() -> None:
    """Sin `name:` explícito y distinto, Compose puede recrear contenedores
    del otro fichero (visto en la práctica: `docker compose -f
    docker-compose.yml up postgres` recreó el postgres de producción)."""
    dev = _load_compose("docker-compose.yml")
    prod = _load_compose("docker-compose.prod.yml")

    dev_name = dev.get("name")
    prod_name = prod.get("name")

    assert dev_name, "docker-compose.yml debe declarar 'name:' de proyecto"
    assert prod_name, "docker-compose.prod.yml debe declarar 'name:' de proyecto"
    assert dev_name != prod_name


# ---------------------------------------------------------------------------
# 8. Coherencia: todo destino de `condition: service_healthy` tiene healthcheck
# ---------------------------------------------------------------------------

def test_every_service_healthy_dependency_has_a_healthcheck() -> None:
    """Un `depends_on: condition: service_healthy` sobre un servicio sin
    healthcheck deja el arranque colgado esperando un estado que nunca llega.

    El caso sutil es `app`: NO declara healthcheck en el compose porque lo
    hereda del `HEALTHCHECK` de su Dockerfile (Docker expone el estado de salud
    del contenedor venga de donde venga). Este test cubre las dos procedencias,
    de modo que retirar el HEALTHCHECK del Dockerfile rompa aquí y no en
    producción.
    """
    compose = _load_compose("docker-compose.prod.yml")
    services = compose["services"]

    def has_healthcheck(name: str) -> bool:
        svc = services[name]
        if svc.get("healthcheck"):
            return True
        build = svc.get("build")
        if not isinstance(build, dict):
            return False
        dockerfile = _ROOT / build.get("context", ".") / build.get("dockerfile", "Dockerfile")
        if not dockerfile.exists():
            return False
        return "HEALTHCHECK" in dockerfile.read_text(encoding="utf-8")

    targets = [
        (name, dep)
        for name, svc in services.items()
        for dep, cond in (svc.get("depends_on") or {}).items()
        if isinstance(cond, dict) and cond.get("condition") == "service_healthy"
    ]
    assert targets, "se esperaba al menos una dependencia service_healthy"

    sin_healthcheck = [
        f"{name} -> {dep}" for name, dep in targets if not has_healthcheck(dep)
    ]
    assert not sin_healthcheck, (
        "servicios esperados como 'healthy' que no definen healthcheck "
        f"(ni en compose ni en su Dockerfile): {sin_healthcheck}"
    )


# ---------------------------------------------------------------------------
# 9. Los volúmenes no dependen del nombre de proyecto
# ---------------------------------------------------------------------------

def test_named_volumes_pin_an_explicit_name() -> None:
    """Compose prefija los volúmenes con el nombre de proyecto. Cuando se
    introdujo `name:` para separar dev de prod, el prefijo pasó de
    `ai_agents_hub_` a `govgenai-dev_` y la base de datos de desarrollo quedó
    huérfana: `up` montaba un volumen vacío mientras los 104 MB de datos
    seguían en el volumen anterior.

    Pinchar `name:` en cada volumen desacopla la identidad del dato del nombre
    del proyecto (y del nombre del directorio), que es lo que debe ser en un
    producto que se instala en máquinas ajenas.
    """
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = _load_compose(filename)
        volumes = compose.get("volumes") or {}
        assert volumes, f"{filename} debe declarar volúmenes con nombre"

        sin_nombre = [
            key for key, cfg in volumes.items()
            if not (isinstance(cfg, dict) and cfg.get("name"))
        ]
        assert not sin_nombre, (
            f"{filename}: volúmenes sin `name:` explícito {sin_nombre}. "
            "Sin él, renombrar el proyecto (o mover el directorio) deja los "
            "datos huérfanos."
        )


# ---------------------------------------------------------------------------
# 10. La imagen de despliegue corre el mismo Python que la suite
# ---------------------------------------------------------------------------

def _version_del_pin() -> str:
    """La versión fijada para el desarrollo, en `server/.python-version`."""
    return (_ROOT / "server" / ".python-version").read_text(encoding="utf-8").strip()


def _versiones_del_dockerfile() -> list[str]:
    """Cada `FROM python:X.Y-...` del Dockerfile de la raíz, en orden."""
    contenido = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    return re.findall(r"^FROM\s+python:(\d+\.\d+)", contenido, re.MULTILINE)


def test_la_imagen_de_despliegue_usa_el_python_que_se_prueba() -> None:
    """Encontrado el 2026-08-21, antes de arrancar el bloque Deploy: la imagen se
    construía sobre `python:3.11-slim` mientras la suite, la integración continua y
    `server/.python-version` iban en 3.13. Dos generaciones de diferencia entre lo
    que se prueba y lo que se enviaría, con un `uv.lock` resuelto para 3.13.

    Puede funcionar, y justamente por eso no se nota: la deriva sólo se manifiesta
    cuando una dependencia se comporta distinto, y entonces el síntoma aparece en
    producción y no en ningún test.

    (El sandbox de scripts va en 3.12 a propósito y no entra aquí: es un servicio
    aparte, con su propio `pyproject.toml` que declara `>=3.12` y su propio
    `uv.lock`. Ahí 3.12 es coherente, no deriva.)
    """
    pin = _version_del_pin()
    etapas = _versiones_del_dockerfile()

    assert etapas, "el Dockerfile de la raíz ya no parte de una imagen `python:X.Y`"
    discrepantes = [v for v in etapas if v != pin]
    assert not discrepantes, (
        f"el Dockerfile construye sobre Python {sorted(set(discrepantes))} y la suite corre "
        f"en {pin} (server/.python-version). Se prueba en un intérprete y se envía otro."
    )


def test_todas_las_etapas_del_dockerfile_usan_la_misma_version() -> None:
    """Un builder y un runtime con Pythons distintos copian un `.venv` construido
    para un intérprete a una imagen con otro. Los `.pyc` y las extensiones nativas
    van ligados a la versión: el fallo no aparece al construir, aparece al importar.
    """
    etapas = _versiones_del_dockerfile()
    assert len(set(etapas)) <= 1, (
        f"las etapas del Dockerfile usan versiones distintas de Python: {etapas}"
    )


def test_la_integracion_continua_usa_el_python_del_pin() -> None:
    """Si CI prueba en una versión y el pin dice otra, la deriva vuelve por donde vino."""
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    versiones = set(re.findall(r"python-version:\s*\[?\s*\"?(\d+\.\d+)\"?", ci))
    pin = _version_del_pin()

    assert versiones, "ci.yml ya no declara `python-version`"
    assert versiones == {pin}, (
        f"CI prueba en {sorted(versiones)} y el pin dice {pin} (server/.python-version)"
    )
