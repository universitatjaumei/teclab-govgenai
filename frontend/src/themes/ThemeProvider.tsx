import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react';
import {
  CLAVE_DEL_TEMA,
  DEFAULT_THEME,
  TEMA_OLVIDADO,
  validateTheme,
  mergeThemes,
  type ThemeConfig,
} from './types';
import { DARK_THEME, UNIVERSITY_THEME, HIGH_CONTRAST_THEME } from './presets';
import { ThemeContext, type ThemeContextValue } from './ThemeContext';
import { injectThemeCSS } from './injectThemeCSS';


const PRESET_THEMES: Record<string, ThemeConfig> = {
  default: DEFAULT_THEME,
  dark: DARK_THEME,
  university: UNIVERSITY_THEME,
  'high-contrast': HIGH_CONTRAST_THEME,
};


interface ThemeProviderProps {
  children: ReactNode;
  initialTheme?: ThemeConfig;
}

/** Trae un tema de una URL **del propio origen**, lo funde con el de por defecto y lo valida.
 *
 * Un tema lleva CSS que se inyecta en la pagina —variables y `customCSS`—, asi que de otro
 * origen seria CSS de un tercero dentro del panel. Por eso se rechaza antes de pedirlo. Hasta el
 * 2026-10-22 el panel lo leia ademas de `?theme=<url>` en la direccion, con cualquier origen, y
 * no lo usaba nada.
 *
 * Lanza si el origen es otro, si la respuesta no es 200 o si el tema tiene errores de
 * validacion: un tema que no valida no se aplica. Quien llama decide que hacer con el fallo.
 */
async function traerTema(url: string): Promise<{ tema: ThemeConfig; avisos: string[] }> {
  if (new URL(url, window.location.href).origin !== window.location.origin) {
    throw new Error('A theme can only be loaded from this site');
  }
  const respuesta = await fetch(url);
  if (!respuesta.ok) {
    throw new Error(`Failed to load theme: ${respuesta.statusText}`);
  }
  const parcial = await respuesta.json();
  const fundido = mergeThemes(DEFAULT_THEME, parcial);
  const validacion = validateTheme(fundido);
  const avisos = [...validacion.errors, ...validacion.warnings];
  if (validacion.errors.length > 0) {
    throw Object.assign(new Error('The theme does not validate'), { avisos });
  }
  return { tema: fundido, avisos };
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({
  children,
  initialTheme,
}) => {
  const [theme, setThemeState] = useState<ThemeConfig>(() => {
    try {
      const saved = localStorage.getItem(CLAVE_DEL_TEMA);
      if (saved) {
        const parsed = JSON.parse(saved);
        return mergeThemes(DEFAULT_THEME, parsed);
      }
    } catch {
      // ignore parse errors
    }
    return initialTheme || DEFAULT_THEME;
  });

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [validationWarnings, setValidationWarnings] = useState<string[]>([]);

  useEffect(() => {
    injectThemeCSS(theme);
  }, [theme]);

  useEffect(() => {
    const volverAlDeSerie = () => setThemeState(initialTheme || DEFAULT_THEME);
    window.addEventListener(TEMA_OLVIDADO, volverAlDeSerie);
    return () => window.removeEventListener(TEMA_OLVIDADO, volverAlDeSerie);
  }, [initialTheme]);

  const setTheme = useCallback((newTheme: ThemeConfig) => {
    const validation = validateTheme(newTheme);
    if (!validation.valid) {
      console.warn('Theme validation failed:', validation.errors);
    }
    setValidationWarnings(validation.warnings);
    setThemeState(newTheme);
    try {
      localStorage.setItem(CLAVE_DEL_TEMA, JSON.stringify(newTheme));
    } catch (e) {
      console.warn('Failed to save theme to localStorage:', e);
    }
  }, []);

  const loadTheme = useCallback(async (url: string): Promise<void> => {
    setIsLoading(true);
    setError(null);

    try {
      const { tema, avisos } = await traerTema(url);
      // No se persiste en localStorage: `loadTheme` es efimero.
      setValidationWarnings(avisos);
      setThemeState(tema);
    } catch (e) {
      const err = e instanceof Error ? e : new Error('Unknown error loading theme');
      setError(err);
      const avisos = (err as Error & { avisos?: string[] }).avisos;
      if (avisos) setValidationWarnings(avisos);
      // Fall back to default on network/HTTP error, foreign origin or invalid theme
      setThemeState(DEFAULT_THEME);
      console.error('Failed to load theme:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const switchTheme = useCallback(async (themeName: string): Promise<void> => {
    const preset = PRESET_THEMES[themeName];
    if (preset) {
      setTheme(preset);
    } else {
      await loadTheme(`/api/themes/${themeName}`);
    }
  }, [setTheme, loadTheme]);

  const resetTheme = useCallback(() => {
    setTheme(DEFAULT_THEME);
    localStorage.removeItem(CLAVE_DEL_TEMA);
  }, [setTheme]);

  const availableThemes = useMemo(() => Object.keys(PRESET_THEMES), []);

  const contextValue = useMemo<ThemeContextValue>(
    () => ({
      theme,
      isLoading,
      error,
      validationWarnings,
      availableThemes,
      setTheme,
      loadTheme,
      switchTheme,
      resetTheme,
    }),
    [theme, isLoading, error, validationWarnings, availableThemes, setTheme, loadTheme, switchTheme, resetTheme]
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      {children}
    </ThemeContext.Provider>
  );
};
