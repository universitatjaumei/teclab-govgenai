import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { noReintentarSiElServidorYaDecidio } from '@/shared/api/reintentos'
import { Suspense, lazy } from 'react'
import { AuthProvider, PrivateRoute } from '@/shared/auth'
import { RutaDeModulo, Aterrizaje, SinAcceso, NoEncontrado } from '@/shared/auth/RutaDeModulo'
import { AppLayout } from '@/admin/AppLayout'
import { HubLayout } from '@/admin/HubLayout'
import { PlataformaLayout } from '@/admin/PlataformaLayout'
import { CurationLayout } from '@/curation/CurationLayout'
import { ThemeProvider } from './themes/ThemeProvider'
import './index.css'
import './themes/base.css'
import '@/shared/i18n'

/**
 * Las páginas se cargan por ruta (CAL.5).
 *
 * Con imports estáticos, Rollup metía las 17 pantallas en un solo bundle de **1,18 MB**: quien
 * entraba a ver una lista de chatbots se descargaba también el constructor de informes, el
 * asistente de scripts y `recharts`. Cada `import()` de aquí es un punto de corte, así que el
 * arranque sólo trae el armazón y la pantalla que se pide.
 *
 * Los envoltorios —`AppLayout`, `HubLayout`, `PrivateRoute`— siguen siendo estáticos: están en
 * todas las rutas, así que separarlos sólo añadiría una espera más sin ahorrar nada.
 *
 * `.then(m => ({ default: ... }))` es necesario porque estos módulos exportan con nombre y
 * `React.lazy` espera un `default`.
 */
const LoginPage = lazy(() => import('@/admin/pages/LoginPage').then(m => ({ default: m.LoginPage })))
const AuthCallbackPage = lazy(() => import('@/admin/pages/AuthCallbackPage').then(m => ({ default: m.AuthCallbackPage })))
const ModulosPage = lazy(() => import('@/admin/pages/ModulosPage').then(m => ({ default: m.ModulosPage })))
const IdentidadVisualPage = lazy(() => import('@/admin/pages/IdentidadVisualPage').then(m => ({ default: m.IdentidadVisualPage })))
const UsuariosPage = lazy(() => import('@/admin/pages/UsuariosPage').then(m => ({ default: m.UsuariosPage })))
const RegistroActividadPage = lazy(() => import('@/admin/pages/RegistroActividadPage').then(m => ({ default: m.RegistroActividadPage })))
const AccessTokensPage = lazy(() => import('@/admin/pages/AccessTokensPage').then(m => ({ default: m.AccessTokensPage })))
const ChatbotsPage = lazy(() => import('@/admin/pages/ChatbotsPage').then(m => ({ default: m.ChatbotsPage })))
const ValoresPorDefectoPage = lazy(() => import('@/admin/pages/ValoresPorDefectoPage').then(m => ({ default: m.ValoresPorDefectoPage })))
const OrganizacionesPage = lazy(() => import('@/admin/pages/OrganizacionesPage').then(m => ({ default: m.OrganizacionesPage })))
const DocumentsPage = lazy(() => import('@/admin/pages/DocumentsPage').then(m => ({ default: m.DocumentsPage })))
const VigenciaPage = lazy(() => import('@/admin/pages/VigenciaPage').then(m => ({ default: m.VigenciaPage })))
const RevisionInteraccionesPage = lazy(() => import('@/admin/pages/RevisionInteraccionesPage').then(m => ({ default: m.RevisionInteraccionesPage })))
const LLMConfigsPage = lazy(() => import('@/admin/pages/LLMConfigsPage').then(m => ({ default: m.LLMConfigsPage })))
const PromptsPage = lazy(() => import('@/admin/pages/PromptsPage').then(m => ({ default: m.PromptsPage })))
const ActivityPromptsPage = lazy(() => import('@/admin/pages/ActivityPromptsPage').then(m => ({ default: m.ActivityPromptsPage })))
const RedaccionLayout = lazy(() => import('@/redaccion/RedaccionLayout').then(m => ({ default: m.RedaccionLayout })))
const CurationSitesPage = lazy(() => import('@/curation/SitesPage').then(m => ({ default: m.SitesPage })))
const CurationAuditPage = lazy(() => import('@/curation/AuditPage').then(m => ({ default: m.AuditPage })))
const CurationFindingsPage = lazy(() => import('@/curation/FindingsPage').then(m => ({ default: m.FindingsPage })))
const CurationPublicationPage = lazy(() => import('@/curation/PublicationPage').then(m => ({ default: m.PublicationPage })))
const TestScenariosPage = lazy(() => import('@/admin/pages/TestScenariosPage').then(m => ({ default: m.TestScenariosPage })))
const ReportTemplateBuilderPage = lazy(() => import('@/redaccion/pages/ReportTemplateBuilderPage').then(m => ({ default: m.ReportTemplateBuilderPage })))
const GenericReportWizard = lazy(() => import('@/redaccion/pages/GenericReportWizard').then(m => ({ default: m.GenericReportWizard })))
const LLMDraftPreviewPage = lazy(() => import('@/redaccion/pages/LLMDraftPreviewPage').then(m => ({ default: m.LLMDraftPreviewPage })))
const ScriptProposalWizardPage = lazy(() => import('@/redaccion/pages/ScriptProposalWizardPage').then(m => ({ default: m.ScriptProposalWizardPage })))
const AdminScriptReviewQueuePage = lazy(() => import('@/redaccion/pages/AdminScriptReviewQueuePage').then(m => ({ default: m.AdminScriptReviewQueuePage })))
const CatalogoDeFuncionesPage = lazy(() => import('@/redaccion/pages/CatalogoDeFuncionesPage').then(m => ({ default: m.CatalogoDeFuncionesPage })))
const RevisionPosteriorPage = lazy(() => import('@/redaccion/pages/RevisionPosteriorPage').then(m => ({ default: m.RevisionPosteriorPage })))
const WorkspacePreview = lazy(() => import('@/redaccion/preview/WorkspacePreview').then(m => ({ default: m.WorkspacePreview })))
const WorkspacePage = lazy(() => import('@/redaccion/pages/WorkspacePage').then(m => ({ default: m.WorkspacePage })))
const UtilidadesLayout = lazy(() => import('@/utilidades/UtilidadesLayout').then(m => ({ default: m.UtilidadesLayout })))
const UtilidadesPdfPage = lazy(() => import('@/utilidades/pages/UtilidadesPdfPage').then(m => ({ default: m.UtilidadesPdfPage })))
const AnonimizarFicheroPage = lazy(() => import('@/utilidades/pages/AnonimizarFicheroPage').then(m => ({ default: m.AnonimizarFicheroPage })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // INF.3 — un 4xx no se reintenta: es una decisión del servidor, no una avería. Con
      // `retry: 2` a secas, un 409 de la vista previa se pedía tres veces antes de que la
      // pantalla pudiera explicar nada, y en ese hueco la consulta no está ni cargando ni en
      // error. Ver `shared/api/reintentos.ts`.
      retry: noReintentarSiElServidorYaDecidio,
      staleTime: 1000 * 60 * 5,
    },
  },
})

const getThemeUrl = (): string | undefined => {
  const params = new URLSearchParams(window.location.search)
  return params.get('theme') ?? undefined
}

/**
 * Espera mientras llega el trozo de la ruta.
 *
 * Antes el `fallback` era `null` porque no había nada que esperar: todo venía en el bundle
 * inicial. Con la carga por ruta, `null` dejaría la pantalla en blanco durante la descarga y
 * parecería que la aplicación se ha colgado.
 */
function CargandoRuta() {
  return (
    <div className="flex items-center justify-center p-12" role="status" aria-live="polite">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted border-t-primary" />
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider themeUrl={getThemeUrl()}>
      {/* DOM.2 — el panel se sirve bajo `/panel/` en la imagen y en la raíz en desarrollo, y
          el prefijo viene de `base` de Vite por `import.meta.env.BASE_URL`. Escrito a mano,
          los tests —que montan en la raíz— dejarían de encontrar sus rutas, y el día que el
          prefijo cambiara habría que acordarse de dos sitios. */}
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <AuthProvider>
          <Suspense fallback={<CargandoRuta />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<AuthCallbackPage />} />
              <Route element={<PrivateRoute />}>
                <Route element={<AppLayout />}>
                  {/* INF.7 — el aterrizaje ya no es `/hub` fijo: cae en el primer modulo
                      concedido. Un trabajador que solo hace informes entra en informes. */}
                  <Route index element={<Aterrizaje />} />
                  <Route path="/sin-acceso" element={<SinAcceso />} />
                  <Route path="/hub" element={<RutaDeModulo modulo="chatbots"><HubLayout /></RutaDeModulo>}>
                    <Route index element={<Navigate to="/hub/chatbots" replace />} />
                    <Route path="chatbots" element={<ChatbotsPage />} />
                    <Route path="valores-por-defecto" element={<ValoresPorDefectoPage />} />
                    <Route path="documents" element={<DocumentsPage />} />
                    <Route path="vigencia" element={<VigenciaPage />} />
                    {/* PLAT.7 — «reports» chocaba de frente con el módulo Informes, que es
                        donde alguien iría a buscarlo; esto es la revisión de interacciones
                        de los asistentes, y la etiqueta ya decía «Revisión». Sin redirección
                        desde la ruta vieja, que AGENTS.md prohíbe los shims. */}
                    <Route path="revision" element={<RevisionInteraccionesPage />} />
                    <Route path="prompts" element={<PromptsPage />} />
                    <Route path="test-scenarios" element={<TestScenariosPage />} />
                  </Route>
                  {/* PLAT.2 — la administración de la plataforma no es del módulo Chatbots.
                      «Modelos LLM» vivía bajo `/hub` mientras su router ya exigía
                      `require_module("plataforma")`: el menú prometía lo que la API negaba.
                      Sin redirecciones desde las rutas viejas, que AGENTS.md prohíbe los shims. */}
                  {/* USR.9 — «Personas» tenía su ruta bajo `/plataforma`, o sea detrás del
                      módulo de administración de la plataforma. Un administrador de
                      organización no lo tiene ni debe tenerlo (ahí están los modelos de LLM,
                      las organizaciones, los tokens y los módulos), así que la capacidad que
                      USR.1 le dio existía por API y no por pantalla. Sin redirección desde la
                      ruta vieja, que AGENTS.md prohíbe los shims. */}
                  <Route path="/personas" element={<RutaDeModulo modulo="personas"><UsuariosPage /></RutaDeModulo>} />
                  {/* REG.6 — modulo propio y no dentro de `plataforma`: el registro es dato
                      operacional de la organizacion (`Deploy: edge`) y aquella pantalla es
                      configuracion de la plataforma (`Deploy: cloud`). Meterlo alli obligaria
                      a dar los modelos de LLM y los tokens para poder dar el registro. */}
                  <Route path="/registro" element={<RutaDeModulo modulo="registro"><RegistroActividadPage /></RutaDeModulo>} />
                  {/* UTL (#190, #191) — lo que hoy se hace en webs que no aseguran el RGPD:
                      unir o partir un PDF, anonimizar un listado para compartirlo. */}
                  <Route path="/utilidades" element={<RutaDeModulo modulo="utilidades"><UtilidadesLayout /></RutaDeModulo>}>
                    <Route index element={<Navigate to="/utilidades/pdf" replace />} />
                    <Route path="pdf" element={<UtilidadesPdfPage />} />
                    <Route path="anonimizar" element={<AnonimizarFicheroPage />} />
                  </Route>
                  <Route path="/plataforma" element={<RutaDeModulo modulo="plataforma"><PlataformaLayout /></RutaDeModulo>}>
                    <Route index element={<Navigate to="/plataforma/modelos" replace />} />
                    {/* REV.11 — sale de /hub: su router ya exigia el modulo plataforma para
                        crear y borrar, asi que aqui vivia detras de la guarda equivocada.
                        Sin redireccion desde la ruta vieja, que AGENTS.md prohibe los shims. */}
                    <Route path="organizaciones" element={<OrganizacionesPage />} />
                    <Route path="modelos" element={<LLMConfigsPage />} />
                    <Route path="prompts-actividad" element={<ActivityPromptsPage />} />
                    <Route path="tokens" element={<AccessTokensPage />} />
                    <Route path="modulos" element={<ModulosPage />} />
                    <Route path="identidad-visual" element={<IdentidadVisualPage />} />
                  </Route>
                  <Route path="/curation" element={<RutaDeModulo modulo="curacion"><CurationLayout /></RutaDeModulo>}>
                    <Route index element={<Navigate to="/curation/sites" replace />} />
                    <Route path="sites" element={<CurationSitesPage />} />
                    <Route path="audit" element={<CurationAuditPage />} />
                    <Route path="findings" element={<CurationFindingsPage />} />
                    <Route path="publish" element={<CurationPublicationPage />} />
                  </Route>
                  {/* Informes: las pantallas existían pero sus rutas estaban sueltas y
                      fuera de todo menú, así que sólo se llegaba escribiendo la URL. */}
                  <Route path="/redaccion" element={<RutaDeModulo modulo="informes"><RedaccionLayout /></RutaDeModulo>}>
                    <Route index element={<Navigate to="/redaccion/builder" replace />} />
                    <Route path="builder" element={<ReportTemplateBuilderPage />} />
                    <Route path="wizard" element={<GenericReportWizard />} />
                    <Route path="draft" element={<LLMDraftPreviewPage />} />
                    <Route path="scripts/wizard" element={<ScriptProposalWizardPage />} />
                    <Route path="scripts/review" element={<AdminScriptReviewQueuePage />} />
                    <Route path="funciones" element={<CatalogoDeFuncionesPage />} />
                    <Route path="funciones/revision" element={<RevisionPosteriorPage />} />
                  </Route>
                  {/* Fuera del layout: es una vista de impresión, sin navegación. */}
                  <Route path="/redaccion/workspaces/:id/preview" element={<WorkspacePreview />} />
                  {/* La pantalla donde se trabaja un informe. Existían todos sus componentes
                      desde 9R y ninguna ruta los montaba (VER.4). */}
                  <Route path="/redaccion/workspaces/:id" element={<WorkspacePage />} />
                </Route>
              </Route>
              {/* REV.5 — una direccion que no existe se dice, no se redirige. Con `Aterrizaje` aqui,
                  cualquier URL equivocada acababa en el primer modulo concedido: un 404
                  disfrazado de redireccion, que es como el enlace de la cola de vigencia
                  parecia llevar a Informes. La raiz sigue aterrizando; esto no. */}
              <Route path="*" element={<NoEncontrado />} />
            </Routes>
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

export default App
