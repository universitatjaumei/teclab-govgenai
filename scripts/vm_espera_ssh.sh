#!/usr/bin/env bash
# Espera a poder entrar por SSH en la VM, y no hace nada más (issue #184).
#
# `gcloud compute ssh` genera una clave efímera en cada invocación y la propaga a la máquina. Si
# se intenta conectar antes de que haya llegado, la conexión se rechaza:
#
#     sa_…@compute.…: Permission denied (publickey).
#     ERROR: (gcloud.compute.ssh) [/usr/bin/ssh] exited with return code [255].
#
# Pasó el 2026-09-28 en el paso «Desplegar» y el 2026-09-23 en «Bajar los secretos», con dos
# pasos que ya habían entrado antes. Los dos despliegues pasaron al relanzarlos sin cambiar nada,
# que es lo que descarta un permiso perdido: eso no se arregla reintentando.
#
# **Este guion sólo conecta.** El comando remoto es `true`, así que repetirlo no puede tener
# ningún efecto en la máquina. Es deliberado y es toda la idea: el comando de verdad lo lanza
# después cada paso, **una sola vez**, fuera de cualquier bucle.
#
# La alternativa —envolver el paso entero en reintentos— sería peor que el problema que arregla.
# El comando remoto de «Desplegar» es `systemctl restart govgenai`, así que reintentar a ciegas
# reinicia el servicio otra vez: 60-90 s más sin responder, y por una causa que puede no tener
# nada que ver con la conexión. Si lo que falló fue el `docker compose` de dentro, repetirlo no
# lo arregla y sí añade una parada.
#
# Si no consigue conectar, sale con error y el paso falla como fallaba antes, con el mismo
# mensaje de `gcloud` a la vista.

set -uo pipefail

: "${VM_NOMBRE:?falta VM_NOMBRE}"
: "${VM_ZONA:?falta VM_ZONA}"

# Tres, que es lo que la issue #184 acordó. Nació con cuatro por descuido mío y lo señaló la
# revisión de la PR #185: no cambia la seguridad de nada, pero el codigo no hacía lo que su
# propia issue prometía, y eso es lo que acaba haciendo que nadie se crea lo escrito.
INTENTOS="${SSH_INTENTOS:-3}"
espera=5

for intento in $(seq 1 "$INTENTOS"); do
  if gcloud compute ssh "$VM_NOMBRE" --zone "$VM_ZONA" --tunnel-through-iap --quiet \
      --command true 2>/tmp/vm_espera_ssh.err; then
    [ "$intento" -gt 1 ] && echo "SSH disponible al intento $intento"
    exit 0
  fi

  motivo="$(tr -d '\r' </tmp/vm_espera_ssh.err | tail -3)"
  echo "intento $intento de $INTENTOS: la VM no acepta la conexión todavía"
  [ -n "$motivo" ] && echo "$motivo"

  if [ "$intento" -lt "$INTENTOS" ]; then
    sleep "$espera"
    # Creciente: la propagación de la clave tarda segundos, no minutos, pero si el motivo es
    # otro —la máquina arrancando, el túnel de IAP— esperar más cuesta menos que fallar.
    espera=$((espera * 2))
  fi
done

echo "::error::No se pudo abrir SSH con $VM_NOMBRE tras $INTENTOS intentos"
exit 1
