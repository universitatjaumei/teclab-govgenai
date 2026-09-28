"""Issue #184 — se reintenta la conexión SSH, y nada que cambie la máquina.

**El fallo.** El despliegue del 2026-09-28 murió con `Permission denied (publickey)` al hacer
`gcloud compute ssh`, y pasó al relanzarlo sin cambiar nada: mismo commit, mismos permisos. Es la
propagación de la clave efímera que `gcloud` genera en cada invocación — si no ha llegado a la VM
cuando se intenta conectar, la conexión se rechaza.

**Y no le pasa sólo a la primera conexión.** Ésa era la suposición al abrir la issue y la
medición la desmintió: el otro despliegue fallido del último mes (run `35913972895`, 2026-09-23)
murió con el mismo error en el paso **«Bajar los secretos y levantar el proxy de Cloud SQL»**, con
dos pasos que ya habían entrado por SSH antes. Así que una sonda al principio no basta: va en cada
paso que entra.

**La condición que pone quien decide, y es la que este test mecaniza**: el reintento se limita al
fallo de conexión. Reintentar el paso entero sería peor que el problema — el comando remoto de
«Desplegar» es `systemctl restart govgenai`, así que un reintento a ciegas **reinicia el servicio
otra vez**, 60-90 s más sin responder, y por una causa que puede no tener nada que ver con la
conexión: si lo que falló fue el `docker compose` de dentro, repetirlo no lo arregla y sí añade una
parada.

De ahí la forma: **una sonda idempotente con reintentos** (`--command true`, que no toca nada) y
después **el comando de verdad una sola vez**. El reintento no puede alcanzar al reinicio porque
vive en un guion que no sabe hacer otra cosa que conectar.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
FLUJO = RAIZ / ".github" / "workflows" / "deploy.yml"
SONDA = RAIZ / "scripts" / "vm_espera_ssh.sh"

#: Lo que delata que un comando cambia el estado de la máquina. No es exhaustivo a propósito:
#: son las formas que hoy aparecen en el despliegue, y sirve para que una nueva no entre en un
#: bucle sin que nadie lo note.
_CAMBIAN_LA_MAQUINA = (
    "systemctl",
    "docker compose",
    "docker exec",
    "rm -",
    "cp ",
    "mv ",
    "tar ",
    "mkdir",
    "tee ",
    "chmod",
)

_ENTRA_POR_SSH = re.compile(r"gcloud compute (?:ssh|scp)")


def _bloques_run() -> list[tuple[str, str]]:
    """Los `run:` del flujo, con el nombre de su paso. Sin dependencias de YAML.

    Se parte por `- name:` y se queda con lo que va detrás de `run:`, que es suficiente para
    este guardarraíl y no obliga a instalar un parser que el resto de la suite no usa.
    """
    texto = FLUJO.read_text(encoding="utf-8")
    bloques: list[tuple[str, str]] = []
    for trozo in re.split(r"\n      - name: ", texto)[1:]:
        nombre = trozo.split("\n", 1)[0].strip()
        if "run: |" in trozo:
            bloques.append((nombre, trozo.split("run: |", 1)[1]))
    return bloques


class TestElGuardarrailMiraLoQueDice:
    """Un recorrido que no encuentra pasos pasa en verde sin haber mirado nada."""

    def test_el_flujo_de_despliegue_existe_y_se_parte_en_pasos(self):
        assert FLUJO.exists(), f"no está {FLUJO}"
        bloques = _bloques_run()

        assert len(bloques) > 10, (
            f"sólo se ven {len(bloques)} pasos con `run:`: este test no está mirando nada"
        )

    def test_sabe_reconocer_una_entrada_por_ssh(self):
        assert _ENTRA_POR_SSH.search('gcloud compute ssh "$VM" --zone x --command "ls"')
        assert _ENTRA_POR_SSH.search("gcloud compute scp fichero vm:/tmp/")
        assert not _ENTRA_POR_SSH.search("gcloud compute instances list")


class TestLaSondaNoSabeHacerNadaMas:
    """Es lo que hace imposible que el reintento toque la máquina."""

    def test_la_sonda_existe(self):
        assert SONDA.exists(), (
            "falta el guion de la sonda: sin él, acotar el reintento a la conexión depende de "
            "que cada paso lo escriba bien"
        )

    def test_la_sonda_no_lleva_ningun_comando_que_cambie_la_maquina(self):
        cuerpo = SONDA.read_text(encoding="utf-8")
        # Sin comentarios: ahí se explica precisamente qué NO se hace.
        codigo = "\n".join(
            linea for linea in cuerpo.splitlines() if not linea.strip().startswith("#")
        )

        culpables = [aguja for aguja in _CAMBIAN_LA_MAQUINA if aguja in codigo]
        assert not culpables, (
            f"la sonda ejecuta {culpables} y está dentro de un bucle de reintentos: "
            "eso es exactamente lo que no puede repetirse"
        )

    def test_los_intentos_son_los_que_la_issue_acordo(self):
        """Tres, no cuatro. La issue decía «hasta tres intentos» y el guion nació con cuatro.

        No es una diferencia de seguridad —un intento más no rompe nada— pero sí es que el código
        no hacía lo que su propia issue prometía, y ésa es la clase de discrepancia que acaba
        haciendo que nadie se crea lo escrito. Lo señaló la revisión de la PR #185.
        """
        codigo = SONDA.read_text(encoding="utf-8")

        assert "SSH_INTENTOS:-3" in codigo, (
            "los intentos por omisión no son tres, que es lo que se acordó en la issue"
        )

    def test_la_sonda_reintenta_de_verdad(self):
        codigo = SONDA.read_text(encoding="utf-8")

        assert re.search(r"for |while |until ", codigo), "no hay bucle: no reintenta nada"
        assert "--command true" in codigo, (
            "la sonda tiene que conectar sin pedir trabajo: `--command true` es lo que la hace "
            "idempotente por construcción"
        )
        assert "sleep" in codigo, "sin espera entre intentos, tres intentos son uno"


class TestNingunPasoEntraSinSondear:

    def test_cada_conexion_sondea_antes(self):
        """**Cada una**, no la primera de cada paso.

        La primera versión miraba sólo la primera coincidencia de cada paso, y por eso pasaba en
        verde con cinco conexiones sin proteger: las dos de «Copiar los ficheros» —`scp` y
        `ssh`—, las dos de «Migraciones» y las tres de comprobación y reversión. Lo señaló la
        revisión de la PR #185, y es la misma forma de medir flojo que este guardarraíl existe
        para evitar: comprobar el primer caso y afirmar el conjunto.

        Si la clave puede no haber propagado en cualquier invocación —y el despliegue del
        2026-09-23 lo demostró fallando en el cuarto paso—, la sonda va delante de cada una o la
        garantía no es uniforme.
        """
        sin_sondear = []
        for nombre, cuerpo in _bloques_run():
            fin_anterior = 0
            for encuentro in _ENTRA_POR_SSH.finditer(cuerpo):
                entre = cuerpo[fin_anterior : encuentro.start()]
                if "vm_espera_ssh.sh" not in entre:
                    linea = cuerpo[encuentro.start() : encuentro.start() + 60].split("\n")[0]
                    sin_sondear.append(f"{nombre}: {linea.strip()}")
                fin_anterior = encuentro.end()

        assert not sin_sondear, (
            "estas conexiones entran por SSH sin sondear antes:\n"
            + "\n".join(f"  - {n}" for n in sin_sondear)
            + "\n\nCada invocación de `gcloud compute ssh|scp` propaga su propia clave: la sonda "
            "va delante de cada una."
        )

    def test_ningun_comando_de_verdad_queda_dentro_de_un_bucle(self):
        """La condición de la issue, mecanizada: el bucle es de la sonda y de nadie más."""
        problemas = []
        for nombre, cuerpo in _bloques_run():
            dentro = 0
            for linea in cuerpo.splitlines():
                pelada = linea.strip()
                if re.match(r"(for|while|until) ", pelada):
                    dentro += 1
                elif pelada in ("done", "done;"):
                    dentro = max(0, dentro - 1)
                elif dentro and _ENTRA_POR_SSH.search(pelada):
                    problemas.append(f"{nombre}: {pelada[:70]}")

        assert not problemas, (
            "hay entradas por SSH dentro de un bucle, y el comando remoto puede cambiar la "
            "máquina:\n" + "\n".join(f"  - {p}" for p in problemas)
            + "\n\nEl único bucle que puede contener una conexión es el de la sonda, que no "
            "pide trabajo."
        )
