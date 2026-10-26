"""El reparto de rutas del dominio institucional (DOM.1).

Cuando el 2026-09-02 apareció el registro A de `normativa.uji.es`, lo primero que servía el
dominio era **el login del panel**. No era un fallo: era exactamente lo que decía la
configuración, porque `(govgenai_rutas)` mandaba al frontend todo lo que no fuera `/api/*` ni
`/health`, y la plantilla del sitio con certificado propio importaba ese fragmento.

El reparto que fija este fichero es el que decidió el usuario ese día:

* **la raíz, la portada pública del corpus** (la del bucket), no el panel;
* **`/panel/`, el panel y su login**, en los dos nombres y bajo el mismo prefijo;
* `/api/*` y `/health`, la aplicación, donde ya estaban;
* todo lo demás, el sitio del corpus en el bucket, **con la forma de sus direcciones intacta**:
  `/html/<norma>.html#art-63` es lo que cita el asistente y lo que la gente guarda.

Tres de las cosas que se comprueban aquí rompen **en silencio**, y por eso tienen test propio:

1. **La raíz del bucket no es su `index.html`.** Devuelve `200` con el listado XML de todos los
   objetos (`ListBucketResult`), porque el mapeo de `/` a `index.html` es la configuración de
   *sitio web* de GCS y eso pide el balanceador que este bloque evitó a propósito. Sin una
   reescritura explícita, `normativa.uji.es/` publica el inventario del bucket.
2. **El proxy tiene que reescribir la cabecera `Host`.** Con la forma virtual-hosted y el Host
   del cliente, GCS no resuelve a qué bucket se refiere y responde 404 a todo el sitio.
3. **Un Caddy que no arranca se lleva por delante los dos nombres**, también el provisional al
   que apuntan las 313 páginas ya publicadas. De ahí el `caddy validate` sobre la configuración
   compuesta con la plantilla sustituida: es la única comprobación que ve el fichero entero.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
VM = RAIZ / "deploy" / "vm"
CADDYFILE = VM / "Caddyfile"
COMPOSE = VM / "docker-compose.vm.yml"
PLANTILLA = VM / "sites.d" / "dominio.caddy.tpl"
DESPLIEGUE = RAIZ / ".github" / "workflows" / "deploy.yml"

BUCKET_DEL_CORPUS = "govgenai-normativa-uji"


def _texto(ruta: Path) -> str:
    assert ruta.is_file(), f"Falta {ruta.relative_to(RAIZ).as_posix()}"
    return ruta.read_text(encoding="utf-8")


def _activas(texto: str, aguja: str) -> list[str]:
    """Líneas que contienen la aguja y NO son comentario."""
    return [
        linea
        for linea in texto.splitlines()
        if aguja in linea and not linea.strip().startswith("#")
    ]


def _fragmento(texto: str, nombre: str) -> str:
    """El cuerpo del fragmento `(nombre)`, contando llaves.

    Se cuenta y no se corta por la primera `}`: el fragmento tiene bloques `handle` dentro, y
    una expresión regular perezosa devolvería sólo hasta el primer cierre.
    """
    inicio = re.search(rf"^\(\s*{re.escape(nombre)}\s*\)\s*\{{", texto, re.M)
    assert inicio, f"No existe el fragmento ({nombre}) en el Caddyfile."
    profundidad = 0
    for i in range(inicio.end() - 1, len(texto)):
        if texto[i] == "{":
            profundidad += 1
        elif texto[i] == "}":
            profundidad -= 1
            if profundidad == 0:
                return texto[inicio.end() : i]
    raise AssertionError(f"El fragmento ({nombre}) no está cerrado.")


# ---------------------------------------------------------------------------
# 1. La raíz es la portada pública, no el panel
# ---------------------------------------------------------------------------


def test_la_raiz_no_va_al_panel() -> None:
    """Es el motivo del bloque: el dominio enseñaba el login."""
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")
    # `frontend:8080` desde la issue #44: la imagen corre sin privilegios y por
    # debajo del 1024 haría falta root. Y el puerto va **entero** a propósito:
    # buscar `frontend:80` seguía casando con `frontend:8080` por subcadena, así
    # que este test pasó el cambio de puerto sin comprobar nada.
    al_frontend = _activas(cuerpo, "frontend:8080")
    assert al_frontend, "El panel tiene que seguir sirviéndose desde algún sitio."
    for linea in al_frontend:
        assert "handle" not in linea, (
            "El `reverse_proxy` al frontend va DENTRO de un `handle` con su prefijo, no en el "
            f"catch-all: {linea.strip()}"
        )
    # El bloque que atrapa todo lo demás no puede ser el del frontend.
    catch_all = re.search(r"^\thandle \{$", cuerpo, re.M)
    assert catch_all, (
        "Tiene que haber un `handle {` sin matcher: es el que manda al bucket todo lo que no "
        "es API, salud ni panel."
    )
    resto = cuerpo[catch_all.end() :]
    hasta_cierre = resto[: resto.index("\n\t}")]
    assert "frontend:8080" not in hasta_cierre, (
        "El catch-all manda al bucket. Si manda al frontend, la raíz del dominio vuelve a ser "
        "el login, que es justo lo que DOM.1 corrige."
    )
    assert "storage.googleapis.com" in hasta_cierre, (
        "El catch-all es el proxy al bucket del corpus."
    )


def test_la_raiz_se_reescribe_al_index_del_bucket() -> None:
    """Sin esto, `normativa.uji.es/` sirve el listado XML de todos los objetos del bucket."""
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")
    reescrituras = _activas(cuerpo, "rewrite")
    assert any(
        re.search(r"rewrite\s+/\s+/index\.html", linea) for linea in reescrituras
    ), (
        "Falta `rewrite / /index.html`. GCS sólo mapea la raíz a `index.html` con la "
        "configuración de sitio web, que necesita un balanceador HTTPS; por el proxy, la raíz "
        "del bucket devuelve 200 con `ListBucketResult` — el inventario completo. Medido el "
        f"2026-09-02 contra https://{BUCKET_DEL_CORPUS}.storage.googleapis.com/"
    )


def test_las_dos_direcciones_amables_de_los_cercadores_redirigen() -> None:
    """`/cercador` y `/gerencia` son lo que la gente escribe; la página canónica sigue siendo una."""
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")
    redirecciones = _activas(cuerpo, "redir")
    esperadas = {
        "/cercador": "/cercador.html",
        "/gerencia": "/cercador_gerencia.html",
    }
    for corta, destino in esperadas.items():
        casadas = [
            linea
            for linea in redirecciones
            if re.search(rf"redir\s+{re.escape(corta)}\s+{re.escape(destino)}", linea)
        ]
        assert casadas, (
            f"Falta `redir {corta} {destino} permanent`. Con una redirección hay una sola "
            f"página canónica; con una copia servida en las dos direcciones, dos."
        )
        assert "permanent" in casadas[0], (
            f"La redirección de {corta} es permanente: la dirección corta no va a cambiar."
        )


# ---------------------------------------------------------------------------
# 2. El panel, bajo prefijo y en los dos nombres
# ---------------------------------------------------------------------------


def test_el_panel_esta_bajo_su_prefijo() -> None:
    """Y con las DOS rutas: la corta que alguien escribe y el comodín de la aplicación.

    `handle` acepta un solo argumento, así que las dos van en un matcher con nombre.
    `handle /panel /panel/*` no es un reparto más estricto: es un error de sintaxis, y con él
    Caddy no arranca. Lo cazó `caddy validate` al escribir este prompt.
    """
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")

    matchers = dict(re.findall(r"^\t(@\w+)\s+path\s+([^\n]+)$", cuerpo, re.M))
    del_panel = {
        nombre: rutas.split() for nombre, rutas in matchers.items() if "/panel" in rutas
    }
    assert del_panel, (
        "Falta un matcher con nombre para `/panel`. El panel es lo único de la aplicación que "
        "no es API, y tiene que estar acotado a su prefijo."
    )
    nombre, rutas = next(iter(del_panel.items()))
    assert "/panel" in rutas, (
        "El prefijo sin barra final tiene que estar en el matcher: quien escriba "
        "`normativa.uji.es/panel` a pelo no debe recibir la portada del corpus."
    )
    assert any(r.startswith("/panel/") for r in rutas), (
        "Y el prefijo con comodín, que es por donde entran las rutas de la aplicación y sus "
        "recursos (`/panel/assets/…`)."
    )
    assert re.search(rf"^\thandle {nombre}\s*\{{", cuerpo, re.M), (
        f"El matcher {nombre} existe pero no lo usa ningún `handle`: el panel quedaría "
        f"servido por el catch-all, o sea por el bucket."
    )


def test_el_prefijo_del_panel_no_se_despoja_en_el_proxy() -> None:
    """La imagen tiene que comportarse igual abierta directa que detrás del proxy.

    `handle_path` quita el prefijo antes de reenviar, y entonces el contenedor sirve en la raíz
    mientras su propio HTML referencia `/panel/assets/…`. Funciona sólo con el proxy delante, y
    esa diferencia se descubre depurando.
    """
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")
    despojos = [
        linea for linea in _activas(cuerpo, "handle_path") if "/panel" in linea
    ]
    assert not despojos, (
        "El prefijo lo sirve el nginx de la imagen (DOM.2), no se le quita por delante: "
        f"{despojos}"
    )


def test_los_dos_nombres_sirven_el_mismo_reparto() -> None:
    """Un reparto copiado en dos sitios divergiría; y aquí divergir es que un nombre se rompa."""
    texto = _texto(CADDYFILE)
    assert _activas(texto, "import govgenai_rutas"), (
        "El bloque del host provisional importa el fragmento."
    )
    assert "import govgenai_rutas" in _texto(PLANTILLA), (
        "Y la plantilla del dominio institucional, el MISMO fragmento: el panel vive bajo el "
        "mismo prefijo en los dos nombres porque `base` es de tiempo de compilación."
    )


def test_la_api_y_la_salud_siguen_en_la_aplicacion() -> None:
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")
    assert "handle /api/*" in cuerpo, "El widget incrustado en el bucket llama a https://<host>/api/v1/…"
    assert "reverse_proxy app:8000" in cuerpo, "El widget incrustado en el bucket llama a https://<host>/api/v1/…"
    assert "handle /health" in cuerpo, (
        "La comprobación de salud del despliegue y la de la vigilancia miran ahí."
    )


# ---------------------------------------------------------------------------
# 3. El bucket: Host reescrito y nombre por entorno
# ---------------------------------------------------------------------------


def test_el_proxy_al_bucket_reescribe_la_cabecera_host() -> None:
    cuerpo = _fragmento(_texto(CADDYFILE), "govgenai_rutas")
    assert _activas(cuerpo, "header_up Host {upstream_hostport}"), (
        "Sin reescribir Host, GCS recibe `normativa.uji.es` y no sabe a qué bucket se refiere: "
        "404 en todo el sitio, incluidas las 313 fichas que cita el asistente."
    )


def test_el_nombre_del_bucket_llega_por_entorno() -> None:
    """El mismo mecanismo tiene que servir a otra organización con otro bucket."""
    texto = _texto(CADDYFILE)
    assert "{$CORPUS_BUCKET}" in texto, (
        "El nombre del bucket se toma de `CORPUS_BUCKET`, no se escribe en el Caddyfile."
    )
    escritos = _activas(texto, BUCKET_DEL_CORPUS)
    assert not escritos, (
        f"El bucket de la UJI escrito a mano en la configuración del proxy: {escritos}"
    )


def test_el_compose_pasa_el_bucket_a_caddy_y_lo_exige() -> None:
    texto = _texto(COMPOSE)
    exigidas = _activas(texto, "CORPUS_BUCKET")
    assert exigidas, (
        "Caddy necesita `CORPUS_BUCKET` en su `environment`: un `{$CORPUS_BUCKET}` sin valor "
        "compone `https://.storage.googleapis.com` y el sitio entero falla sin decir por qué."
    )
    assert any(":?" in linea for linea in exigidas), (
        "Con la forma `${CORPUS_BUCKET:?falta CORPUS_BUCKET}`, el despliegue se detiene con un "
        f"mensaje en vez de levantar un proxy roto: {exigidas}"
    )


def test_el_despliegue_escribe_el_bucket_en_la_configuracion() -> None:
    texto = _texto(DESPLIEGUE)
    assert _activas(texto, "CORPUS_BUCKET="), (
        "`.env.despliegue` lo escribe el workflow desde las variables del repositorio; si la "
        "línea no está ahí, la variable no llega a la máquina."
    )
    assert "vars.CORPUS_BUCKET" in texto, (
        "Y su valor sale de `vars`, como los otros identificadores: no es un secreto, pero "
        "tampoco se escribe en el repositorio."
    )


# ---------------------------------------------------------------------------
# 4. Que Caddy arranque, que es lo que no se puede probar leyendo
# ---------------------------------------------------------------------------


def _par_autofirmado(nombre: str) -> tuple[bytes, bytes]:
    """Certificado y clave en PEM, para que `caddy validate` tenga algo que cargar."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre)])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(sujeto)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(nombre)]), critical=False)
        .sign(clave, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        clave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker no está disponible")
def test_caddy_valida_la_configuracion_compuesta(tmp_path: Path) -> None:
    """Con la plantilla sustituida y un certificado de prueba, como en la máquina.

    Un `caddy validate` sobre el Caddyfile a secas no ve el sitio del dominio, que es un
    `import` de un glob. Y un error ahí no degrada: Caddy no arranca, y con él se van los dos
    nombres.
    """
    sitios = tmp_path / "sites.d"
    sitios.mkdir()
    plantilla = _texto(PLANTILLA).replace("{{HOST}}", "normativa.uji.es")
    (sitios / "normativa.uji.es.caddy").write_text(plantilla, encoding="utf-8")

    tls = tmp_path / "tls"
    tls.mkdir()
    # Un par autofirmado de verdad, y no dos ficheros con la cabecera PEM puesta a mano:
    # `caddy validate` **aprovisiona** la aplicación TLS, así que carga el certificado y falla
    # con «failed to find any PEM data in certificate input» si no lo puede leer. Ese rojo no
    # diría nada del reparto de rutas, que es lo que este test mide.
    cert, clave = _par_autofirmado("normativa.uji.es")
    (tls / "fullchain.pem").write_bytes(cert)
    (tls / "privkey.pem").write_bytes(clave)

    (tmp_path / "Caddyfile").write_text(_texto(CADDYFILE), encoding="utf-8")

    montado = tmp_path.as_posix()
    if re.match(r"^[A-Za-z]:", montado):  # Windows: /c/Users/… es lo que entiende Docker
        montado = "/" + montado[0].lower() + montado[2:]

    def _caddy(*orden: str) -> tuple[int, str]:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{montado}:/etc/caddy:ro",
                "-e", "GOVGENAI_HOST=34-175-38-129.sslip.io",
                "-e", "CORPUS_BUCKET=un-bucket-de-prueba",
                "caddy:2.8-alpine",
                *orden,
                "--config", "/etc/caddy/Caddyfile",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    codigo, salida = _caddy("caddy", "validate")
    # Las dos formas de decir lo mismo. `shutil.which("docker")` encuentra el ejecutable de
    # Docker Desktop aunque el motor esté parado, así que el skip de arriba no cubre este caso y
    # lo que queda es leer el error. En Linux llega como «Cannot connect to the Docker daemon»;
    # en Windows, como «failed to connect to the docker API at npipe://…», y con el demonio
    # apagado este test daba ROJO en vez de saltarse — un rojo de entorno en el cierre de
    # cualquier prompt, que es como se acaba ignorando la suite entera.
    demonio_parado = ("Cannot connect to the Docker daemon", "failed to connect to the docker API")
    if codigo != 0 and any(marca in salida for marca in demonio_parado):
        pytest.skip("el demonio de Docker no está en marcha")
    assert codigo == 0, f"`caddy validate` falla:\n{salida}"

    # `validate` dice que arranca; lo que NO dice es a qué nombres responde. Eso está en la
    # configuración adaptada, y comprobarlo es lo que impide que un cambio deje fuera uno de
    # los dos — el provisional, al que apuntan las 313 páginas ya publicadas, o el
    # institucional, que es el que se estrena.
    codigo, adaptada = _caddy("caddy", "adapt")
    assert codigo == 0, f"`caddy adapt` falla:\n{adaptada}"
    for nombre in ("34-175-38-129.sslip.io", "normativa.uji.es"):
        assert nombre in adaptada, (
            f"{nombre} no aparece en la configuración adaptada: ese nombre dejaría de "
            f"servirse.\n{adaptada}"
        )
