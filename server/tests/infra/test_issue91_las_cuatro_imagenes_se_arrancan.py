"""Las cuatro imágenes que se despliegan se comprueban arrancadas, no sólo construidas.

**El hueco (issue #91).** De las cuatro, CI arrancaba dos. Para `sandbox` y `mcp` el verde
significaba «compila», no «arranca» — que es exactamente la forma del incidente del 2026-09-15:
`uvicorn` no estaba declarado, la imagen construía y `docker run` daba `rc=127`. IMG.1 cerró eso
para la aplicación y el frontend y dejó el mismo agujero dos imágenes más allá.

Y en producción el MCP **no tenía comprobación de salud en ningún sitio**: ni `HEALTHCHECK` en su
`Dockerfile` ni `healthcheck` en el compose, y el paso que decide si el despliegue se revierte no
lo miraba. Si se quedara sirviendo errores, Docker seguiría diciendo `Up` y nadie se enteraría
hasta que alguien intentara usarlo.

**Lo que hace delicado este arreglo, y es la razón de que el primer test sea el que es.** La
respuesta sana del MCP **no es un 200**. Con un `GET /mcp` sin la cabecera del transporte devuelve
**406**, y desde un host que no está en `GOVGENAI_MCP_ALLOWED_HOSTS` devuelve **421**. Las dos
significan «en pie». Lo que significa «muerto» es **no responder**.

Una sonda que espere 200 ahí se pone roja con el servicio sano, y una sonda que siempre pasa no
vigila nada. Por eso lo primero que se fija aquí no es que exista la sonda, sino **qué distingue**.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
CI = RAIZ / ".github" / "workflows" / "ci.yml"
DEPLOY = RAIZ / ".github" / "workflows" / "deploy.yml"
DOCKERFILE_MCP = RAIZ / "mcp_server" / "Dockerfile"
DOCKERFILE_SANDBOX = RAIZ / "services" / "script_sandbox" / "Dockerfile"


def _sonda_del_dockerfile(ruta: Path) -> str:
    """El mandato de `HEALTHCHECK`, tal cual está escrito."""
    # Por líneas y no con una expresión regular de continuaciones: la primera versión usaba
    # `HEALTHCHECK[^\n]*(?:\\\n[^\n]*)*` y **se quedaba con la primera línea**, porque `[^\n]*`
    # se come también la barra de continuación y ya no queda ninguna para el grupo siguiente.
    # Un extractor que devuelve media instrucción hace fallar tests que hablan de otra cosa.
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    for i, linea in enumerate(lineas):
        if not linea.lstrip().startswith("HEALTHCHECK"):
            continue
        bloque = [linea]
        while bloque[-1].rstrip().endswith("\\") and i + 1 < len(lineas):
            i += 1
            bloque.append(lineas[i])
        return "\n".join(bloque)
    return ""


class _Responde:
    """Un servidor mínimo que contesta con el código que se le diga."""

    def __init__(self, codigo: int) -> None:
        self.codigo = codigo

        manejador = self

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):  # lo fija BaseHTTPRequestHandler
                self.send_response(manejador.codigo)
                self.end_headers()

            def log_message(self, *_):  # silencio
                return

        self._servidor = HTTPServer(("127.0.0.1", 0), _H)
        self.puerto = self._servidor.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self._servidor.shutdown()
        self._servidor.server_close()


def _puerto_libre() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sonda_dice_vivo(puerto: int) -> bool:
    """Ejecuta **la misma orden** que el `HEALTHCHECK`, apuntada a otro puerto.

    Se extrae del `Dockerfile` y se sustituye el puerto: así lo que se prueba es la orden que
    corre en producción y no una reescritura suya, que es donde se cuela la divergencia.
    """
    orden = _sonda_del_dockerfile(DOCKERFILE_MCP)
    codigo = re.search(r'python -c "(.+?)"', orden, re.DOTALL)
    assert codigo, f"no encuentro el `python -c` dentro del HEALTHCHECK:\n{orden}"
    guion = codigo.group(1).replace("8080", str(puerto))
    return subprocess.run([sys.executable, "-c", guion], capture_output=True, check=False).returncode == 0


class TestLaSondaDelMcpDistingueVivoDeMuerto:
    """Lo primero, porque es lo que puede estar mal sin que nadie lo note."""

    def test_un_406_es_estar_vivo(self) -> None:
        """La respuesta del transporte a un GET sin su cabecera `Accept`."""
        with _Responde(406) as servidor:
            assert _sonda_dice_vivo(servidor.puerto), (
                "la sonda da por muerto un 406, que es la respuesta SANA del MCP a un GET sin "
                "la cabecera del transporte: se pondría roja con el servicio en pie"
            )

    def test_un_421_es_estar_vivo(self) -> None:
        """Lo que responde el guardián de host desde dentro del contenedor."""
        with _Responde(421) as servidor:
            assert _sonda_dice_vivo(servidor.puerto)

    def test_un_200_tambien(self) -> None:
        with _Responde(200) as servidor:
            assert _sonda_dice_vivo(servidor.puerto)

    def test_sin_respuesta_es_estar_muerto(self) -> None:
        """Y éste es el que hace que la sonda sirva de algo."""
        assert not _sonda_dice_vivo(_puerto_libre()), (
            "la sonda dice que está vivo con NADA escuchando: no vigila nada"
        )

    def test_un_500_es_estar_muerto(self) -> None:
        """**El hueco de la primera versión**, señalado en la revisión de la PR #110.

        La sonda hacía `sys.exit(0 if status else 1)`, y cualquier entero no nulo es verdadero:
        un MCP que arrancara y respondiera 500 por un fallo de la aplicación seguiría `healthy`
        y **no dispararía la reversión** que #91 venía a cubrir.

        Mi razonamiento era «cualquier respuesta significa que el proceso está en pie», y eso es
        cierto del proceso y falso del servicio. Lo que importa es si sirve.
        """
        with _Responde(500) as servidor:
            assert not _sonda_dice_vivo(servidor.puerto), (
                "la sonda da por sano un 500: el MCP puede estar roto y el despliegue no "
                "revertirá"
            )

    def test_un_404_tambien_es_estar_muerto(self) -> None:
        """Si `/mcp` deja de existir, el servicio no sirve aunque el proceso viva."""
        with _Responde(404) as servidor:
            assert not _sonda_dice_vivo(servidor.puerto)


class TestLasDosImagenesTienenSonda:
    def test_el_mcp_declara_healthcheck_en_su_dockerfile(self) -> None:
        """En el `Dockerfile` y no en el compose, como `app` y `frontend`.

        Así vale para cualquiera que despliegue esto con otro orquestador; una sonda escrita
        sólo en nuestro compose se queda en nuestra máquina.
        """
        assert _sonda_del_dockerfile(DOCKERFILE_MCP), (
            "`mcp_server/Dockerfile` no declara `HEALTHCHECK`: en producción el contenedor sale "
            "`Up` sin estado de salud, y eso es indistinguible de sano"
        )

    def test_el_sandbox_declara_healthcheck_en_su_dockerfile(self) -> None:
        assert _sonda_del_dockerfile(DOCKERFILE_SANDBOX), (
            "`services/script_sandbox/Dockerfile` no declara `HEALTHCHECK`"
        )


def _pasos_del_job(fichero: Path, job: str) -> list[dict]:
    datos = yaml.safe_load(fichero.read_text(encoding="utf-8"))
    return datos["jobs"][job].get("steps", [])


class TestCiArrancaLasCuatro:
    def test_el_job_arranca_el_sandbox(self) -> None:
        corre = "\n".join(p.get("run") or "" for p in _pasos_del_job(CI, "imagen"))
        assert "govgenai/sandbox:ci" in corre, (
            "el job `imagen` construye la imagen del sandbox y no la arranca: su verde dice "
            "«compila», no «arranca»"
        )
        assert "docker run" in corre, (
            "el job `imagen` construye la imagen del sandbox y no la arranca: su verde dice "
            "«compila», no «arranca»"
        )

    def test_el_job_arranca_el_mcp(self) -> None:
        # `re.DOTALL` y no `[^\n]*`: el `docker run` del MCP lleva varias opciones y se escribe
        # con continuaciones de línea. La primera versión de esta comprobación exigía que todo
        # cupiera en una línea y ponía rojo un job que sí arrancaba la imagen.
        corre = "\n".join(p.get("run") or "" for p in _pasos_del_job(CI, "imagen"))
        assert re.search(r"docker run.{0,400}?govgenai/mcp:ci", corre, re.DOTALL), (
            "el job `imagen` construye la imagen del MCP y no la arranca"
        )

    def test_el_resumen_no_promete_mas_de_lo_que_comprueba(self) -> None:
        """El resumen decía «las cuatro imágenes», y se leía como «las cuatro comprobadas»."""
        pasos = _pasos_del_job(CI, "imagen")
        resumen = next((p for p in pasos if p.get("name") == "Resumen"), None)
        assert resumen is not None
        texto = resumen.get("run") or ""
        assert "arrancada" in texto or "arrancadas" in texto


class TestElDespliegueMiraElMcp:
    def test_el_paso_que_revierte_comprueba_el_mcp(self) -> None:
        """Sin esto, el MCP puede estar muerto y la reversión automática no se dispara."""
        # Se busca por lo que **hace** y no por su nombre exacto: mi primera versión buscaba
        # «vuelve atrás» y el paso se llama «volver atrás», así que no encontraba nada y el
        # test fallaba por su propio texto en vez de por el del workflow.
        pasos = _pasos_del_job(DEPLOY, "desplegar")
        paso = next((p for p in pasos if "Volviendo a la configuración anterior" in (p.get("run") or "")), None)
        assert paso is not None, "no encuentro el paso que comprueba y revierte"
        assert "govgenai_mcp" in (paso.get("run") or ""), (
            "el paso que decide si se revierte no mira el MCP: podría quedarse sirviendo "
            "errores y el despliegue saldría en verde"
        )
