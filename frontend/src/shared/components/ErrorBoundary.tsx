import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Lo que se enseña cuando una pantalla revienta al pintarse (#278).
 *
 * Sin esto, un error de render dejaba la SPA entera en blanco: menú incluido, así que tampoco se
 * podía ir a otra sección. Va **por zona** —alrededor del contenido de cada ruta—, de modo que lo
 * que cae es la pantalla y el resto del panel sigue funcionando.
 */
function AvisoDeFallo({ reintentar }: { reintentar: () => void }) {
  const { t } = useTranslation('common')
  return (
    <div role="alert" data-testid="pantalla-con-fallo" className="space-y-2 p-4 border rounded-md">
      <h2 className="font-semibold">{t('error_boundary_title')}</h2>
      <p className="text-sm text-muted-foreground">{t('error_boundary_body')}</p>
      <button type="button" className="text-sm px-3 py-1 rounded border" onClick={reintentar}>
        {t('error_boundary_retry')}
      </button>
    </div>
  )
}

interface Props {
  children: ReactNode
}

interface Estado {
  fallo: Error | null
}

export class ErrorBoundary extends Component<Props, Estado> {
  state: Estado = { fallo: null }

  static getDerivedStateFromError(fallo: Error): Estado {
    return { fallo }
  }

  componentDidCatch(fallo: Error, info: ErrorInfo) {
    // En la consola, para quien depura: la pantalla sólo dice que falló.
    console.error('Fallo al pintar la pantalla', fallo, info.componentStack)
  }

  render() {
    if (this.state.fallo) {
      return <AvisoDeFallo reintentar={() => this.setState({ fallo: null })} />
    }
    return this.props.children
  }
}
