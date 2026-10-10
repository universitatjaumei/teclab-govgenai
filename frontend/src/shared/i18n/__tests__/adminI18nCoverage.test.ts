/**
 * CAL.4 — Cobertura i18n del panel de administración.
 *
 * Tres cosas distintas se comprueban aquí, y las tres se escapan de un test de render:
 *
 * 1. **Paridad de claves** entre `es`, `ca` y `en`. Sin esto, el catalán se queda atrás en
 *    silencio: i18next cae al idioma por defecto y la pantalla se ve *bien*, sólo que en
 *    castellano. Un usuario que ha elegido catalán no distingue eso de un descuido.
 * 2. **Que no queden claves muertas.** Un diccionario que acumula claves sin consumidor
 *    obliga a traducir a tres idiomas texto que nadie va a leer.
 * 3. **Que las pantallas no lleven castellano incrustado**, que es la vía por la que las
 *    claves dejan de crearse.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import es from '@/shared/i18n/locales/es/admin.json'
import ca from '@/shared/i18n/locales/ca/admin.json'
import en from '@/shared/i18n/locales/en/admin.json'

const SRC = resolve(__dirname, '../../..')

type Diccionario = Record<string, unknown>

function claves(objeto: Diccionario, prefijo = ''): string[] {
  return Object.entries(objeto).flatMap(([k, v]) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? claves(v as Diccionario, `${prefijo}${k}.`)
      : [`${prefijo}${k}`],
  )
}

function ficherosFuente(): string[] {
  const out: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) {
        if (entry === 'node_modules' || entry === 'generated' || entry === 'locales') continue
        walk(full)
        continue
      }
      if (/\.(ts|tsx)$/.test(entry)) out.push(full)
    }
  }
  walk(SRC)
  return out
}

const codigo = ficherosFuente()
  .map((f) => readFileSync(f, 'utf-8'))
  .join('\n')

describe('CAL.4 — i18n del panel admin', () => {
  it('should_have_key_parity_across_es_ca_en_admin_namespace', () => {
    const kEs = claves(es as Diccionario).sort()
    const kCa = claves(ca as Diccionario).sort()
    const kEn = claves(en as Diccionario).sort()

    const faltanCa = kEs.filter((k) => !kCa.includes(k))
    const sobranCa = kCa.filter((k) => !kEs.includes(k))
    const faltanEn = kEs.filter((k) => !kEn.includes(k))
    const sobranEn = kEn.filter((k) => !kEs.includes(k))

    expect(faltanCa, `Claves sin traducir al catalán:\n  ${faltanCa.join('\n  ')}`).toEqual([])
    expect(sobranCa, `Claves en catalán que ya no existen en castellano: ${sobranCa.join(', ')}`).toEqual([])
    expect(faltanEn, `Claves sin traducir al inglés:\n  ${faltanEn.join('\n  ')}`).toEqual([])
    expect(sobranEn, `Claves en inglés que ya no existen en castellano: ${sobranEn.join(', ')}`).toEqual([])
  })

  it('should_not_keep_unused_admin_i18n_keys', () => {
    // Las claves dinámicas (`t(\`hub.availability_${estado}\`)`) no aparecen literales en el
    // código: se comprueban por prefijo, que es lo que de verdad garantiza que hay consumidor.
    const PREFIJOS_DINAMICOS = [
      'nav.',
      'hub.availability_',
      // LANG.2 — los modos de política de lengua los enumera el servidor y la pantalla
      // itera: `t(`hub.language_mode_${m.valor}`)`. Escribir las claves literales aquí
      // sería congelar el catálogo en React, que es justo lo que el bloque quita.
      'hub.language_mode_',
      'hub.test_scenarios.verdict_',
      // IDE.4 — el rol y el origen de cada persona se pintan iterando lo que devuelve el
      // servidor: `t(`plataforma.usuarios.roles.${persona.role}`)`. La clave literal no
      // aparece en el código, y tiene que ser así: si estuviera escrita, la pantalla dejaría
      // de pintar lo que el contrato mande y volvería a decidir ella.
      'plataforma.usuarios.roles.',
      'plataforma.usuarios.origenes.',
      // IDE.5 — el tipo de sujeto de cada concesión, iterando lo que devuelve el servidor.
      'plataforma.modulos.tipos.',
      // PLAT.3 — la etiqueta de cada valor por defecto, iterando lo que devuelve el
      // servidor: `t(`hub.valores_por_defecto.campos.${campo}`)`.
      'hub.valores_por_defecto.campos.',
      // PLAT.6 — el nivel de la cascada visual, que la pantalla ofrece según el rol y usa
      // también para decir de qué nivel hereda cada campo.
      'plataforma.identidad_visual.niveles.',
      // REV.7 — el módulo de cada actividad, iterando lo que devuelve el servidor: los
      // módulos del desplegable salen de los datos y el catálogo crece cuando se cablea un
      // consumidor nuevo, así que escribir las claves literales aquí sería congelarlo.
      'hub.activity_prompts.modulos.',
      // #252 — lo que le queda a una organización que no se puede borrar, iterando el
      // `detail.pendiente` del 409: `t(`hub.organizacion_pendiente_${clave}`, { count })`.
      'hub.organizacion_pendiente_',
    ]

    // Las formas plurales de i18next (`x_one` / `x_other`) tampoco aparecen literales: el
    // código llama a `t('x', { count })` y es i18next quien elige el sufijo. Se busca la
    // clave base, que es el consumidor real — y así una forma huérfana, sin `t('x')` en
    // ningún sitio, sigue saltando.
    const usada = (clave: string) => {
      const sufijo = clave.replace(/^hub\./, '')
      return codigo.includes(`'${clave}'`)
        || codigo.includes(`"${clave}"`)
        || codigo.includes(`admin:${clave}`)
        || codigo.includes(`'hub.${sufijo}'`)
    }

    const muertas = claves(es as Diccionario).filter((k) => {
      if (PREFIJOS_DINAMICOS.some((p) => k.startsWith(p))) return false
      const base = k.replace(/_(one|other|zero|two|few|many)$/, '')
      return !usada(k) && !(base !== k && usada(base))
    })

    expect(
      muertas,
      `Claves del diccionario sin ningún consumidor en el código:\n  ${muertas.join('\n  ')}`,
    ).toEqual([])
  })

  it('should_not_render_hardcoded_spanish_in_llmconfigs_page', () => {
    const page = readFileSync(join(SRC, 'admin/pages/LLMConfigsPage.tsx'), 'utf-8')

    const literales = [
      'Proveedores de Modelos (Dinámicos)',
      'Nuevo Proveedor',
      'No hay proveedores definidos.',
      'Eliminar Proveedor',
      'Editar Proveedor',
      'ID del Proveedor',
      'Nombre a mostrar',
      'Tipo de API',
      'Base URL (Opcional)',
      'API Key (Opcional)',
      'Si se especifica, se usará en lugar de la variable de entorno.',
      'Escribir manualmente...',
      '-- Seleccionar de la lista --',
      'Lista de modelos obtenida dinámicamente para el proveedor seleccionado.',
      'Nombre de la variable de entorno que contiene la clave (opcional si el proveedor ya la tiene).',
      'Por defecto: 12000 (salida). La ventana de contexto para long context se controla aparte (128K).',
      'Max tokens (salida)',
      'Acciones',
    ]

    const presentes = literales.filter((l) => page.includes(l))
    expect(
      presentes,
      `Literales en castellano todavía incrustados en LLMConfigsPage:\n  ${presentes.join('\n  ')}`,
    ).toEqual([])
  })

  /**
   * Sustituye a `should_render_interval_options_via_i18n` del plan: `INTERVAL_OPTIONS` y
   * `SPIDER_TYPES` desaparecieron con el panel de fuentes en CAL.2. Las constantes con
   * etiqueta que quedan en la pantalla de documentos son `LANGUAGE_OPTIONS` y
   * `RETRIEVAL_LABELS`, y son las que el prompt pide resolver con `t()` en el render.
   */
  it('should_render_language_options_via_i18n', () => {
    const constantes = readFileSync(join(SRC, 'admin/documents/constants.ts'), 'utf-8')

    // El array guarda claves, no texto: la etiqueta se resuelve al pintar.
    expect(constantes).not.toMatch(/'Auto-detectar'|'Español'|'Català'|'English'/)
    expect(constantes).not.toMatch(/'Vectorial'|'Contexto largo'|'Agéntico'/)
    expect(constantes).toMatch(/labelKey/)
  })

  it('should_not_keep_admin_keys_only_as_inline_default', () => {
    // CAL.4.1 — el test de paridad no caza esto por construcción: una clave que sólo vive
    // como segundo argumento de la llamada a t() con un texto por defecto nunca falta en
    // es/admin.json porque nunca llegó a estar ahí. Aquí se barre el código en busca de ese
    // patrón exacto.
    const kEs = new Set(claves(es as Diccionario))
    const patron = /t\(\s*'(hub\.[\w.]+)'\s*,\s*'/g

    const huerfanas = new Set<string>()
    for (const fuente of codigo.matchAll(patron)) {
      const clave = fuente[1]
      if (!kEs.has(clave)) huerfanas.add(clave)
    }

    expect(
      [...huerfanas].sort(),
      `Claves usadas como t('clave', 'default') que no están en es/admin.json:\n  ${[...huerfanas].join('\n  ')}`,
    ).toEqual([])
  })

  it('should_associate_labels_with_inputs', () => {
    // Un <label> sin `htmlFor` no nombra a nada: el lector de pantalla lee el campo como
    // «cuadro de edición» y quien navega con teclado no puede pulsar la etiqueta para
    // enfocarlo. Se exige en las pantallas que CAL.4 toca.
    const paginas = ['admin/pages/LLMConfigsPage.tsx', 'admin/documents/UploadDropzone.tsx']

    const huerfanos: string[] = []
    for (const rel of paginas) {
      const src = readFileSync(join(SRC, rel), 'utf-8')
      const total = (src.match(/<label\b/g) ?? []).length
      const conFor = (src.match(/<label\b[^>]*htmlFor=/g) ?? []).length
      if (total !== conFor) huerfanos.push(`${rel}: ${total - conFor} de ${total} <label> sin htmlFor`)
    }

    expect(huerfanos, `Etiquetas que no nombran a su campo:\n  ${huerfanos.join('\n  ')}`).toEqual([])
  })
})
