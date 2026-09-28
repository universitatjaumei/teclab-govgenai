import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  useGetThemesApiV1HubThemesGet,
  useCreateThemeApiV1HubThemesPost,
  useUpdateThemeApiV1HubThemesThemeIdPut,
  useUploadThemeLogoApiV1HubThemesThemeIdLogoPost,
  useGetThemeDefaultsApiV1HubThemesDefaultsGet,
  getGetThemesApiV1HubThemesGetQueryKey,
  getGetResolvedThemeApiV1HubThemesResolvedGetQueryKey,
} from '@/shared/api/generated/hub-themes/hub-themes'
import { useListOrganizacionesApiV1HubOrganizacionesGet } from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'
import { useAuth } from '@/shared/auth'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'

type Nivel = 'plataforma' | 'organizacion' | 'chatbot'
type Config = Record<string, Record<string, unknown>>

/** Lo que acepta el servidor (SEC.6 + PLAT/marca): sin SVG y sin WebP, y por qué. */
const FORMATOS = 'image/png,image/jpeg'
/** El mismo tope que `validate_upload`. Comprobarlo aquí ahorra subir un mega para nada. */
const TOPE_BYTES = 1024 * 1024

/**
 * Familias sugeridas, no impuestas: va en un `<datalist>` y no en un `<select>`.
 *
 * Un tema con una familia que no esté en esta lista tiene que seguir mostrando la suya. Con un
 * `<select>` la perdería en silencio al abrir la pantalla, que es la peor manera de perder una
 * decisión de diseño ajena.
 */
const TIPOGRAFIAS = [
  "'Inter', sans-serif",
  "'Roboto', sans-serif",
  "'Open Sans', sans-serif",
  "'Source Sans 3', sans-serif",
  "'Lato', sans-serif",
  "system-ui, sans-serif",
  "Georgia, serif",
  "'Source Serif 4', serif",
  "'JetBrains Mono', monospace",
]

interface Tema {
  id: string
  name: string
  organizacion_id: string | null
  chatbot_id: string | null
  config: Config
}

/** El tema de un nivel, o `null` si ese nivel no tiene uno propio todavía. */
function temaDelNivel(
  temas: Tema[],
  nivel: Nivel,
  organizacionId: string,
  chatbotId: string
): Tema | null {
  if (nivel === 'plataforma') {
    return temas.find((t) => !t.organizacion_id && !t.chatbot_id) ?? null
  }
  if (nivel === 'organizacion') {
    return (
      temas.find((t) => t.organizacion_id === organizacionId && !t.chatbot_id) ?? null
    )
  }
  return temas.find((t) => t.chatbot_id === chatbotId) ?? null
}

/**
 * La identidad visual de la plataforma, de una organización o de un asistente (PLAT.6).
 *
 * La cascada existía y funcionaba; lo que no había era dónde configurarla. El logotipo se subía
 * por `curl` y los colores solo se tocaban escribiendo JSON a mano en un `<textarea>` cuyo
 * destino, además, no lo leía nadie (`HubOrganizacion.theme_config`, que retira PLAT.7).
 *
 * **Los campos se iteran del contrato.** Si estuvieran escritos aquí, la pantalla dejaría de
 * pintar lo que el contrato mande y volvería a decidir ella — el mismo error que la marca
 * importada como código.
 *
 * **Lo heredado se ve y no se congela.** Se dice de qué nivel viene cada valor que este nivel no
 * define, y al guardar **solo se manda lo propio**: copiar la paleta del padre dejaría al hijo
 * con valores que ya no le siguen, y nadie se enteraría hasta que el padre cambiara.
 *
 * **Y hay vista previa sobre el fondo real de la barra lateral**, que es el motivo por el que la
 * prueba manual de la marca necesitaba a una persona: un logotipo con letras oscuras pasa todos
 * los tests y se lee fatal sobre el azul del panel.
 */
export function IdentidadVisualPage() {
  const { t } = useTranslation('admin')
  const qc = useQueryClient()
  const { user } = useAuth()
  const esSuperadmin = user?.role === 'superadmin'

  const { data: temas = [], isLoading } = useGetThemesApiV1HubThemesGet()
  /**
   * **De aquí sale la lista de campos**, no de los temas que existan.
   *
   * Lo destapó la verificación en navegador: en el nivel de plataforma de una instalación
   * recién levantada no hay tema propio ni padre del que heredar, así que iterando los temas
   * la pantalla no ofrecía ni un campo — justo en el estado en el que alguien entra por
   * primera vez. Escribir la lista aquí la desincronizaría del contrato en el primer color
   * nuevo; el servidor publica sus valores por omisión y esta pantalla los recorre.
   */
  const { data: valoresDelContrato } = useGetThemeDefaultsApiV1HubThemesDefaultsGet()
  const { data: organizaciones = [] } = useListOrganizacionesApiV1HubOrganizacionesGet()
  const { data: chatbots = [] } = useChatbotsDeLaOrganizacion()

  const niveles: Nivel[] = esSuperadmin
    ? ['plataforma', 'organizacion', 'chatbot']
    : ['organizacion', 'chatbot']

  /**
   * `?organizacion=<id>` viene del enlace de la pantalla de organizaciones (PLAT.3): quien
   * pulsa allí ya ha elegido de qué organización habla, y volver a preguntárselo en un selector
   * es rehacer trabajo hecho.
   */
  const [parametros] = useSearchParams()
  const pedida = parametros.get('organizacion')

  const [nivel, setNivel] = useState<Nivel>(pedida ? 'organizacion' : niveles[0])
  const [organizacionId, setOrganizacionId] = useState(pedida ?? '')
  const [chatbotId, setChatbotId] = useState('')
  const [edicion, setEdicion] = useState<Config>({})
  const [error, setError] = useState<string | null>(null)
  /** El fichero elegido, para poder decirlo en su propia línea y no en la del botón. */
  const [nombreFichero, setNombreFichero] = useState<string | null>(null)

  const lista = temas as unknown as Tema[]
  const orgElegida = organizacionId || String(organizaciones[0]?.id ?? '')
  const botElegido = chatbotId || String(chatbots[0]?.id ?? '')

  const propio = temaDelNivel(lista, nivel, orgElegida, botElegido)
  /** El nivel de arriba, para saber de dónde viene lo que este no define. */
  const padre = useMemo(() => {
    if (nivel === 'plataforma') return null
    if (nivel === 'organizacion') return temaDelNivel(lista, 'plataforma', '', '')
    return temaDelNivel(lista, 'organizacion', orgElegida, '')
      ?? temaDelNivel(lista, 'plataforma', '', '')
  }, [lista, nivel, orgElegida])

  /**
   * El **nivel** del que se hereda, no el nombre de la fila del tema. En el navegador se leía
   * «Heredado de Tema» —el nombre por omisión de la fila— y eso no le dice nada a quien
   * configura: lo que necesita saber es de qué escalón de la cascada le viene el valor.
   */
  const nivelDelPadre = useMemo(() => {
    if (!padre) return null
    if (!padre.organizacion_id && !padre.chatbot_id) return 'plataforma' as const
    if (!padre.chatbot_id) return 'organizacion' as const
    return 'chatbot' as const
  }, [padre])

  const etiquetaDelPadre = nivelDelPadre
    ? t(`plataforma.identidad_visual.niveles.${nivelDelPadre}` as Parameters<typeof t>[0])
    : ''

  const { mutate: guardar, isPending: guardando } = useUpdateThemeApiV1HubThemesThemeIdPut()
  const { mutate: crear } = useCreateThemeApiV1HubThemesPost()
  const { mutate: subirLogo } = useUploadThemeLogoApiV1HubThemesThemeIdLogoPost()

  /**
   * Se invalidan **las dos** consultas, y la segunda es la que importa (REV.9).
   *
   * Esta pantalla invalidaba sólo la lista de temas, así que al guardar un color el formulario
   * se refrescaba y el panel seguía igual: los colores del panel salen de `/themes/resolved`,
   * que es otra consulta y se quedaba en caché. Había que recargar a mano para ver el cambio,
   * y eso se lee como «no se ha guardado».
   */
  const invalidar = () => {
    void qc.invalidateQueries({ queryKey: getGetThemesApiV1HubThemesGetQueryKey() })
    void qc.invalidateQueries({ queryKey: getGetResolvedThemeApiV1HubThemesResolvedGetQueryKey() })
  }

  /** Lo que este nivel define, más lo editado sin guardar. Nunca lo del padre. */
  function propios(grupo: string): Record<string, unknown> {
    return { ...(propio?.config?.[grupo] ?? {}), ...(edicion[grupo] ?? {}) }
  }

  /**
   * Todo lo que se pinta: los campos del contrato, más lo que traigan este nivel y su padre.
   *
   * El contrato manda la lista; los otros dos entran por si un tema guardado a mano lleva una
   * clave que el contrato ya no declara — mejor mostrarla y poder cambiarla que esconder un
   * valor que sigue aplicándose.
   */
  const delContrato = (valoresDelContrato?.config ?? {}) as Config

  function visibles(grupo: string): string[] {
    return [
      ...new Set([
        ...Object.keys(delContrato[grupo] ?? {}),
        ...Object.keys(padre?.config?.[grupo] ?? {}),
        ...Object.keys(propios(grupo)),
      ]),
    ]
  }

  function valor(grupo: string, campo: string): string {
    const mio = propios(grupo)[campo]
    if (mio !== undefined) return String(mio)
    const heredado = padre?.config?.[grupo]?.[campo]
    if (heredado !== undefined && heredado !== null) return String(heredado)
    // Último recurso: el valor por omisión del contrato. No se anuncia como «heredado de» un
    // nivel, porque no viene de ninguno: decir «heredado de Plataforma» cuando no hay tema de
    // plataforma seria mentirle a quien configura.
    return String(delContrato[grupo]?.[campo] ?? '')
  }

  /**
   * Heredado significa **que un nivel de arriba lo define**, no simplemente que este no lo
   * defina. Un valor por omisión del contrato no viene de ningún nivel, y anunciarlo como
   * «heredado de Plataforma» cuando no hay tema de plataforma le mentiría a quien configura.
   */
  function esHeredado(grupo: string, campo: string): boolean {
    if (propios(grupo)[campo] !== undefined) return false
    const arriba = padre?.config?.[grupo]?.[campo]
    return arriba !== undefined && arriba !== null
  }

  function editar(grupo: string, campo: string, nuevo: string) {
    setEdicion((previo) => ({ ...previo, [grupo]: { ...(previo[grupo] ?? {}), [campo]: nuevo } }))
  }

  function alGuardar() {
    if (!propio) {
      crear(
        {
          data: {
            name: t('plataforma.identidad_visual.nombre_por_defecto'),
            organizacion_id: nivel === 'plataforma' ? null : orgElegida,
            chatbot_id: nivel === 'chatbot' ? botElegido : null,
            // Solo lo editado: un tema nuevo no nace con la paleta del padre copiada.
            config: { name: 'institucional', ...edicion } as never,
          },
        },
        { onSuccess: () => { setEdicion({}); invalidar() } }
      )
      return
    }
    // **Solo lo propio.** Mandar lo heredado lo convertiría en propio para siempre.
    const config = { ...propio.config }
    for (const [grupo, campos] of Object.entries(edicion)) {
      config[grupo] = { ...(config[grupo] ?? {}), ...campos }
    }
    guardar(
      { themeId: propio.id, data: { config: config as never } },
      { onSuccess: () => { setEdicion({}); invalidar() } }
    )
  }

  /**
   * El `accept` filtra el diálogo del sistema, no lo que llega: se puede arrastrar el fichero o
   * elegir «todos los archivos». Sin este corte el servidor responde 400 y la pantalla no dice
   * por qué — y el megabyte se sube igual antes de que lo rechacen.
   *
   * **REV.4 — y sin tema propio también se puede.** Antes esto exigía `propio` y el control
   * salía deshabilitado: en una instalación recién levantada el nivel de plataforma no tiene
   * tema, así que la única forma de subir el logotipo era guardar antes unos colores que quizá
   * nadie quería tocar. Ahora el tema se crea al vuelo y el fichero se sube sobre el que salga.
   */
  function alElegirFichero(evento: React.ChangeEvent<HTMLInputElement>) {
    const fichero = evento.target.files?.[0]
    if (!fichero) return

    if (!FORMATOS.split(',').includes(fichero.type)) {
      setError(t('plataforma.identidad_visual.formato_rechazado', { tipo: fichero.type }))
      return
    }
    if (fichero.size > TOPE_BYTES) {
      setError(t('plataforma.identidad_visual.demasiado_grande'))
      return
    }

    setError(null)
    setNombreFichero(fichero.name)

    if (propio) {
      subirLogo({ themeId: propio.id, data: { file: fichero } }, { onSuccess: invalidar })
      return
    }

    crear(
      {
        data: {
          name: t('plataforma.identidad_visual.nombre_por_defecto'),
          organizacion_id: nivel === 'plataforma' ? null : orgElegida,
          chatbot_id: nivel === 'chatbot' ? botElegido : null,
          // Sólo lo editado sin guardar, si lo hay. El tema nace para colgar de él el
          // logotipo, no para congelar la paleta del padre.
          config: { name: 'institucional', ...edicion } as never,
        },
      },
      {
        onSuccess: (creado: { id: string }) => {
          setEdicion({})
          invalidar()
          subirLogo({ themeId: creado.id, data: { file: fichero } }, { onSuccess: invalidar })
        },
      }
    )
  }

  const marca = (propios('branding') ?? {}) as { logoUrl?: string; logoAlt?: string }
  const marcaHeredada = (padre?.config?.branding ?? {}) as { logoUrl?: string; logoAlt?: string }
  const logoUrl = marca.logoUrl ?? marcaHeredada.logoUrl
  const logoAlt = marca.logoAlt ?? marcaHeredada.logoAlt

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold">{t('plataforma.identidad_visual.titulo')}</h2>
        <p className="text-sm text-muted-foreground">
          {t('plataforma.identidad_visual.alcance')}
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="iv_nivel" className="text-sm font-medium">
            {t('plataforma.identidad_visual.nivel')}
          </label>
          <select
            id="iv_nivel"
            value={nivel}
            onChange={(e) => { setNivel(e.target.value as Nivel); setEdicion({}) }}
            className="rounded-md border px-2 py-1.5 text-sm bg-background"
          >
            {niveles.map((n) => (
              <option key={n} value={n}>
                {t(`plataforma.identidad_visual.niveles.${n}` as Parameters<typeof t>[0])}
              </option>
            ))}
          </select>
        </div>

        {nivel === 'organizacion' && (
          <div className="flex flex-col gap-1">
            <label htmlFor="iv_org" className="text-sm font-medium">
              {t('plataforma.identidad_visual.organizacion')}
            </label>
            <select
              id="iv_org"
              value={orgElegida}
              onChange={(e) => setOrganizacionId(e.target.value)}
              className="rounded-md border px-2 py-1.5 text-sm bg-background"
            >
              {organizaciones.map((o) => (
                <option key={o.id} value={String(o.id)}>{o.name}</option>
              ))}
            </select>
          </div>
        )}

        {nivel === 'chatbot' && (
          <div className="flex flex-col gap-1">
            <label htmlFor="iv_bot" className="text-sm font-medium">
              {t('plataforma.identidad_visual.chatbot')}
            </label>
            <select
              id="iv_bot"
              value={botElegido}
              onChange={(e) => setChatbotId(e.target.value)}
              className="rounded-md border px-2 py-1.5 text-sm bg-background"
            >
              {chatbots.map((c) => (
                <option key={c.id} value={String(c.id)}>{c.name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {isLoading ? (
        <p>{t('plataforma.identidad_visual.cargando')}</p>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-4">
            <section className="space-y-2">
              <h3 className="text-sm font-semibold">
                {t('plataforma.identidad_visual.colores')}
              </h3>
              {visibles('colors').map((campo) => (
                <div
                  key={campo}
                  data-testid={`campo-${campo}`}
                  className="flex items-center gap-3 text-sm"
                >
                  <label htmlFor={`color-${campo}`} className="w-48 shrink-0 font-mono text-xs">
                    {campo}
                  </label>
                  <input
                    id={`color-${campo}`}
                    data-testid={`color-${campo}`}
                    type="color"
                    value={valor('colors', campo)}
                    onChange={(e) => editar('colors', campo, e.target.value)}
                    className="h-7 w-12 rounded border"
                  />
                  {/* De dónde viene lo que este nivel no define. Una cascada que no se ve es
                      una cascada que se configura a ciegas. */}
                  {esHeredado('colors', campo) && (
                    <span className="text-xs text-muted-foreground">
                      {t('plataforma.identidad_visual.heredado_de', { nivel: etiquetaDelPadre })}
                    </span>
                  )}
                </div>
              ))}
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-semibold">
                {t('plataforma.identidad_visual.tipografia')}
              </h3>
              {visibles('typography').map((campo) => (
                <div key={campo} className="flex items-center gap-3 text-sm">
                  <label htmlFor={`tipo-${campo}`} className="w-48 shrink-0 font-mono text-xs">
                    {campo}
                  </label>
                  <input
                    id={`tipo-${campo}`}
                    data-testid={`tipo-${campo}`}
                    // Sugerencias solo donde tienen sentido: `fontSize` o `lineHeight` no son
                    // familias, y ofrecerle «Georgia, serif» como tamaño sería ruido.
                    list={campo === 'fontFamily' ? 'iv_familias' : undefined}
                    value={valor('typography', campo)}
                    onChange={(e) => editar('typography', campo, e.target.value)}
                    className="flex-1 rounded border px-2 py-1 text-sm"
                  />
                  {esHeredado('typography', campo) && (
                    <span className="text-xs text-muted-foreground">
                      {t('plataforma.identidad_visual.heredado_de', { nivel: etiquetaDelPadre })}
                    </span>
                  )}
                </div>
              ))}
              <datalist id="iv_familias">
                {TIPOGRAFIAS.map((familia) => (
                  <option key={familia} value={familia} />
                ))}
              </datalist>
            </section>

            <button
              type="button"
              onClick={alGuardar}
              disabled={guardando}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
            >
              {t('plataforma.identidad_visual.guardar')}
            </button>
          </div>

          <div className="space-y-4">
            <section className="space-y-2">
              <h3 className="text-sm font-semibold">
                {t('plataforma.identidad_visual.logotipo')}
              </h3>
              {/* El control nativo no se puede estilar ni traducir —«Tria un fitxer» lo pone
                  el navegador, en su idioma, y va pegado al «no s'ha triat cap fitxer»—, así
                  que se oculta a la vista con `sr-only` (no a los lectores de pantalla, que
                  siguen viendo un input de fichero) y quien pulsa lo hace sobre la etiqueta. */}
              <input
                id="iv_logo"
                data-testid="logo-file"
                type="file"
                accept={FORMATOS}
                onChange={alElegirFichero}
                className="sr-only"
              />
              <label
                htmlFor="iv_logo"
                data-testid="logo-boton"
                className="inline-block cursor-pointer rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-accent focus-within:ring-2 focus-within:ring-ring"
              >
                {t('plataforma.identidad_visual.elegir_fichero')}
              </label>
              {/* En su propia línea: en el control nativo el nombre del fichero comparte
                  renglón con el botón y se lee como parte de él. */}
              <p data-testid="logo-nombre" className="text-xs text-muted-foreground">
                {nombreFichero ?? t('plataforma.identidad_visual.sin_fichero')}
              </p>
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
              {/* Los límites reales, y por qué el SVG queda fuera. Sin decirlo, quien lo
                  intente creerá que la aplicación está rota. */}
              <p className="text-xs text-muted-foreground">
                {t('plataforma.identidad_visual.limites')}
              </p>
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-semibold">
                {t('plataforma.identidad_visual.previa')}
              </h3>
              {/* Sobre `bg-sidebar`, el fondo real del panel: un logotipo con letras oscuras
                  pasa todos los tests automáticos y se lee fatal sobre el azul. */}
              <div
                data-testid="previa-de-la-marca"
                className="bg-sidebar text-sidebar-foreground rounded-md p-4 w-56"
              >
                {logoUrl ? (
                  <img src={logoUrl} alt={logoAlt ?? ''} className="h-8 w-auto" />
                ) : (
                  <p className="h-8 font-semibold leading-8">
                    {logoAlt ?? t('plataforma.identidad_visual.sin_marca')}
                  </p>
                )}
                <div
                  className="mt-3 h-6 rounded"
                  style={{ backgroundColor: valor('colors', 'primary') || undefined }}
                />
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
