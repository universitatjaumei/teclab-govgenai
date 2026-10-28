import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // Los `cva(...)` de los componentes de interfaz son constantes, no componentes, y
      // Fast Refresh sabe convivir con ellas. Sin esta opcion habria que sacarlas a un
      // fichero aparte por nada (issue #47).
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      // El guión bajo delante ya es la convención de este código para decir «esto se declara
      // y no se usa **a propósito**»: el `_omitida` de `payloadDeProveedor`, que existe para
      // quitar una clave del objeto, o el `_failure_kind` de una firma que tiene que aceptar
      // el argumento aunque no lo mire. Sin este patrón, la forma de callar al linter sería
      // reescribir un idioma correcto, que es peor que configurar la regla (issue #47).
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],

      // --- Las tres reglas que sí cazan defectos, como AVISO y con techo (issue #47) ---
      //
      // `set-state-in-effect` (bucles de renderizado), `exhaustive-deps` (estado que se queda
      // viejo) y `refs` (acceso durante el render) son defectos de verdad, y hay **20
      // repartidos en 15 componentes**. Arreglarlos cambia comportamiento en tiempo de
      // ejecución y cada uno pide verificarse en navegador: es un bloque propio, no un efecto
      // colateral de encender el linter.
      //
      // Se dejaron en `warn` con `--max-warnings` fijado en la cifra de cada momento, para que un
      // hallazgo nuevo tumbara el job aunque los viejos siguieran. **Desde #281 el techo es 0**:
      // no queda ninguno, así que cualquier aviso nuevo se arregla al aparecer.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/refs': 'warn',

      // Informativo del compilador de React —«compilación omitida por librería incompatible»—:
      // no es un defecto, es que el compilador no puede optimizar ese trozo.
      'react-hooks/incompatible-library': 'warn',

      // Fast Refresh es una comodidad **del desarrollo local**, no una regla de corrección: no
      // afecta a lo que se construye ni a lo que se sirve. Aun así no queda ningún aviso (#281):
      // el contexto del tema, su `useTheme` y lo que no es componente viven en ficheros aparte.
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },

  // En los tests, `any` es el idioma: un *mock* se tipa así y forzar un tipo exacto obliga a
  // reescribir la firma del doble cada vez que cambia la real. **Medido antes de decidirlo**:
  // los 61 `no-explicit-any` del proyecto estaban **todos aquí** y producción tenía **cero**,
  // así que esto no tapa nada — describe dónde está permitido y dónde no (issue #47).
  {
    files: ['**/__tests__/**', '**/*.test.{ts,tsx}', 'src/test-setup.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
])
