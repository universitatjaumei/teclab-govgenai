/**
 * Por qué un hallazgo es un hallazgo, en una línea (CUR.8).
 *
 * Del usuario: «cuando se dice que están desactualizadas o potencialmente desactualizadas, se
 * debería decir la razón (que la fecha que se indica como fecha de actualización es anterior a x
 * años, meses o el criterio que se utilice)». Sin esto la columna «Tipo» es una etiqueta que hay que
 * creerse, y una lista de trabajo que no se puede comprobar no se revisa: se descarta entera.
 *
 * Todo sale de la **señal del hallazgo**, no de la configuración de hoy: el criterio es de cada
 * sitio y se puede cambiar, así que leerlo al pintar diría con qué se juzgaría ahora y no con qué se
 * juzgó entonces.
 */

interface HallazgoConSenal {
  finding_type: string
  signal?: Record<string, unknown> | null
}

type Traductor = (clave: string, opciones?: Record<string, unknown>) => string

/** Un número que puede no venir: los hallazgos anteriores a CUR.8 no traen umbral. */
function numero(valor: unknown): number | null {
  return typeof valor === 'number' && Number.isFinite(valor) ? valor : null
}

function texto(valor: unknown): string | null {
  return typeof valor === 'string' && valor.trim() ? valor : null
}

export function razonDelHallazgo(hallazgo: HallazgoConSenal, t: Traductor): string {
  const s = hallazgo.signal ?? {}

  switch (hallazgo.finding_type) {
    case 'stale': {
      const fecha = texto(s.date)
      const dias = numero(s.age_days)
      const umbral = numero(s.threshold)
      const partes: string[] = []
      if (fecha) partes.push(t('reason_stale_date', { fecha: new Date(fecha).toLocaleDateString() }))
      if (dias !== null) partes.push(t('reason_stale_age', { dias }))
      if (umbral !== null) partes.push(t('reason_stale_threshold', { umbral }))
      return partes.join(' · ')
    }

    case 'thin': {
      const tokens = numero(s.token_count)
      const umbral = numero(s.threshold)
      if (tokens === null) return ''
      return umbral === null
        ? t('reason_thin_short', { tokens })
        : t('reason_thin', { tokens, umbral })
    }

    case 'navigation': {
      const enlaces = numero(s.enlaces)
      const propio = numero(s.texto_propio)
      if (enlaces === null || propio === null) return ''
      return t('reason_navigation', { enlaces, propio })
    }

    case 'duplicate':
    case 'contradiction': {
      const similitud = numero(s.similarity)
      const explicacion = texto(s.explanation)
      const partes: string[] = []
      if (similitud !== null) partes.push(t('reason_similarity', { porcentaje: Math.round(similitud * 100) }))
      if (explicacion) partes.push(explicacion)
      return partes.join(' · ')
    }

    case 'crawl_error': {
      const clase = texto(s.kind)
      const intentos = numero(s.attempts)
      const partes: string[] = []
      // Las causas que el rastreo sabe distinguir (RAS.3). Una que no conozca se dice tal cual en
      // vez de traducirse a un texto genérico que perdería la información.
      if (clase) {
        const conocidas = ['not_found', 'transient', 'client_error', 'unknown']
        partes.push(conocidas.includes(clase) ? t(`reason_error_${clase}`) : clase)
      }
      if (intentos !== null) partes.push(t('reason_error_attempts', { intentos }))
      const mensaje = texto(s.error_message)
      if (mensaje) partes.push(mensaje.slice(0, 120))
      return partes.join(' · ')
    }

    case 'version_series': {
      const cuantas = numero(s.count)
      return cuantas === null ? '' : t('reason_series', { cuantas })
    }

    case 'needs_javascript': {
      const tokens = numero(s.token_count)
      return tokens === null ? t('reason_needs_js_short') : t('reason_needs_js', { tokens })
    }

    case 'content_updated': {
      const fecha = texto(s.date) ?? texto(s.changed_at)
      return fecha
        ? t('reason_updated', { fecha: new Date(fecha).toLocaleDateString() })
        : t('reason_updated_short')
    }

    // DIN.4 — la página desapareció y este apartado no retira solo: la decisión es de quien cura.
    case 'page_gone':
      return t('reason_page_gone')

    // DIN.4 — la salvaguarda paró una retirada entera, y las cifras son lo que permite juzgar si
    // el portal cambió de verdad o el rastreo salió mal. Sin ellas el aviso no dice nada.
    case 'retirada_masiva_detenida': {
      const bajas = numero(s.bajas)
      const ambito = numero(s.ambito)
      const proporcion = numero(s.proporcion)
      return bajas === null || ambito === null
        ? t('reason_retirada_masiva_detenida_short')
        : t('reason_retirada_masiva_detenida', {
            bajas,
            ambito,
            proporcion: Math.round((proporcion ?? bajas / ambito) * 100),
          })
    }

    // DIN.5 — la puerta de calidad no la dejó entrar al corpus. El motivo es lo único que hace
    // accionable el aviso: sin él, quien cura ve una página que no se publica y no sabe por qué.
    case 'auto_ingesta_detenida': {
      const motivos = Array.isArray(s.motivos) ? (s.motivos as string[]) : []
      return t('reason_auto_ingesta_detenida', {
        motivos: motivos
          .map((m) => t(`type_${m}` as Parameters<typeof t>[0]))
          .join(', '),
      })
    }

    default:
      return texto(s.explanation) ?? ''
  }
}

/** La URL de la segunda página de un hallazgo que habla de dos, si la hay. */
export function urlRelacionada(hallazgo: HallazgoConSenal): string | null {
  return texto((hallazgo.signal ?? {}).related_url)
}
