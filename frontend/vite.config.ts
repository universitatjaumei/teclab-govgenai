import { defineConfig } from 'vitest/config'
// `loadEnv` no lo reexporta `vitest/config`: sale de `vite`.
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

/** Destino del proxy de desarrollo.
 *
 * Configurable por `VITE_API_TARGET` (`.env.local`) para quien necesite otro puerto, pero el
 * defecto es el bueno: es el puerto en el que `arranque.bat` levanta el backend.
 *
 * Si el 8000 da `WinError 10048`, no es que haga falta otro puerto: lo retiene el árbol de
 * procesos de un uvicorn `--reload` anterior cuyo arranque falló, con el socket en estado
 * `Bound` (invisible para `netstat | findstr LISTENING`). Se mata el árbol entero y se sigue
 * en el 8000. Detalle en la nota del 2026-08-20 de `planificacion/PROJECT_STATE.md`.
 */
const DESTINO_API_POR_DEFECTO = 'http://localhost:8000'

/** Prefijo bajo el que se sirve el panel (DOM.2).
 *
 * Desde que `normativa.uji.es/` sirve la portada pública del corpus, el panel vive en
 * `/panel/`. Es un `base` y no una regla del proxy porque **Vite escribe las URL de los
 * recursos en el HTML en tiempo de compilación**: sin esto, la imagen pide `/assets/…`, y esas
 * URL servidas bajo el prefijo caen en el catch-all del proxy —o sea en el bucket— y devuelven
 * 404 con la página en blanco.
 *
 * El defecto es la raíz a propósito: `arranque.bat`, `.env.example`, la documentación de
 * metodología y una docena de guiones de pruebas manuales de bloques ya cerrados dan por hecho
 * que en desarrollo el panel está en `http://localhost:5173/`. Quien quiera desarrollar con el
 * mismo prefijo que producción, pone `VITE_BASE_PATH=/panel/` en `frontend/.env.local`.
 *
 * El valor lo consume además el `basename` del `BrowserRouter`, que lo lee de
 * `import.meta.env.BASE_URL`: así el prefijo se dice una sola vez y no hay ningún literal en el
 * código de la aplicación.
 */
const BASE_POR_DEFECTO = '/'

export default defineConfig(({ mode }) => ({
  base: loadEnv(mode, process.cwd(), '').VITE_BASE_PATH || BASE_POR_DEFECTO,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    proxy: {
      '/api': {
        target: loadEnv(mode, process.cwd(), '').VITE_API_TARGET || DESTINO_API_POR_DEFECTO,
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      input: {
        admin: 'index.html',
        widget: 'widget.html',
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/.{idea,git,cache,output,temp}/**',
      'src/__tests__/a11y/**',
    ],
  },
}))
