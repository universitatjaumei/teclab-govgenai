# Stage 1: Builder — compila el SPA con Vite (misma major que CI, ver ci.yml)
FROM node:26-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vacío a propósito: en producción el frontend y el backend se sirven en el
# mismo origen (nginx reenvía /api/* a "app"), así que las llamadas relativas
# no necesitan conocer un host público en tiempo de build.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}

# El prefijo del panel (DOM.2). El defecto es el de PRODUCCIÓN y no el de
# desarrollo, porque esta imagen ES producción: `deploy.yml` la construye con
# `docker build ./frontend` a secas, sin pasar build-args.
#
# Vite escribe las URL de los recursos en el HTML al compilar, así que este valor
# tiene que coincidir con la ruta bajo la que nginx sirve el `dist` (más abajo) y
# con la que el proxy encamina al frontend (`deploy/vm/Caddyfile`). Son tres
# ficheros y una sola verdad; lo comprueba
# `server/tests/infra/test_dom2_el_panel_bajo_su_prefijo.py`.
ARG VITE_BASE_PATH="/panel/"
ENV VITE_BASE_PATH=${VITE_BASE_PATH}

RUN npm run build


# Stage 2: Runtime — nginx sirviendo los estáticos + proxy same-origin del API
#
# **Sin privilegios (issue #44).** La imagen oficial de nginx arranca como root, y ésta era
# la única de las cuatro del proyecto que no declaraba usuario —las otras van con `appuser`
# o `65534`—. No es un agujero, es defensa en profundidad: el día que una vulnerabilidad de
# nginx permita ejecutar algo, la diferencia entre hacerlo como root o como un usuario sin
# privilegios es la diferencia entre un susto y un incidente. Y esto se publica como ejemplo
# de despliegue para administraciones, así que es lo que copiará quien lo tome de plantilla.
#
# **Añadir `USER` a la imagen oficial no era la alternativa barata: no arranca.** Dentro de
# un contenedor, escuchar por debajo del 1024 exige root o `CAP_NET_BIND_SERVICE`. Por eso
# esta imagen escucha en el **8080**, y por eso el cambio toca cinco ficheros y no uno:
# `nginx.conf`, el `EXPOSE` y la sonda de aquí, el `reverse_proxy` del `Caddyfile` y el
# mapeo del compose de producción. Son cinco sitios y un solo número; lo comprueba
# `server/tests/infra/test_issue44_el_frontend_no_corre_como_root.py`, porque si uno se
# queda atrás el panel devuelve 502 y el fallo aparece en el despliegue, no aquí.
FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

# El `dist` va al SUBDIRECTORIO del prefijo, no a la raíz. Así `/panel/assets/x.js`
# es un fichero que existe de verdad y no el `index.html` devuelto por el fallback
# del SPA: cuando eso pasa, el navegador dice «Unexpected token '<'» y nadie mira
# nginx. Y así la imagen se comporta igual abierta directa que detrás del proxy,
# sin depender de que alguien le quite el prefijo por delante.
COPY --from=builder /app/dist /usr/share/nginx/html/panel
COPY nginx.conf /etc/nginx/conf.d/default.conf

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/healthz || exit 1

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
