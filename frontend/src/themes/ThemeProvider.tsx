import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react';
import {
  DEFAULT_THEME,
  validateTheme,
  mergeThemes,
  type ThemeConfig,
} from './types';
import { DARK_THEME, UNIVERSITY_THEME, HIGH_CONTRAST_THEME } from './presets';

interface ThemeContextValue {
  theme: ThemeConfig;
  isLoading: boolean;
  error: Error | null;
  validationWarnings: string[];
  availableThemes: string[];
  setTheme: (theme: ThemeConfig) => void;
  loadTheme: (url: string) => Promise<void>;
  switchTheme: (themeName: string) => Promise<void>;
  resetTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const PRESET_THEMES: Record<string, ThemeConfig> = {
  default: DEFAULT_THEME,
  dark: DARK_THEME,
  university: UNIVERSITY_THEME,
  'high-contrast': HIGH_CONTRAST_THEME,
};

const STORAGE_KEY = 'chatbot-theme';

function camelToKebab(str: string): string {
  return str.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
}

function generateCSSVariables(theme: ThemeConfig): string {
  const variables: string[] = [];

  for (const [key, value] of Object.entries(theme.colors)) {
    variables.push(`--color-${camelToKebab(key)}: ${value};`);
  }

  variables.push(`--font-family: ${theme.typography.fontFamily};`);
  variables.push(`--font-family-mono: ${theme.typography.fontFamilyMono};`);
  variables.push(`--font-size-xs: ${theme.typography.fontSizeXs};`);
  variables.push(`--font-size-sm: ${theme.typography.fontSizeSmall};`);
  variables.push(`--font-size: ${theme.typography.fontSize};`);
  variables.push(`--font-size-md: ${theme.typography.fontSizeMd};`);
  variables.push(`--font-size-lg: ${theme.typography.fontSizeLarge};`);
  variables.push(`--font-size-xl: ${theme.typography.fontSizeXl};`);
  variables.push(`--font-size-xxl: ${theme.typography.fontSizeXxl};`);
  variables.push(`--font-weight-light: ${theme.typography.fontWeightLight};`);
  variables.push(`--font-weight: ${theme.typography.fontWeight};`);
  variables.push(`--font-weight-medium: ${theme.typography.fontWeightMedium};`);
  variables.push(`--font-weight-bold: ${theme.typography.fontWeightBold};`);
  variables.push(`--line-height: ${theme.typography.lineHeight};`);
  variables.push(`--line-height-tight: ${theme.typography.lineHeightTight};`);
  variables.push(`--line-height-relaxed: ${theme.typography.lineHeightRelaxed};`);

  for (const [key, value] of Object.entries(theme.spacing)) {
    variables.push(`--spacing-${key}: ${value};`);
  }

  for (const [key, value] of Object.entries(theme.borderRadius)) {
    variables.push(`--radius-${key}: ${value};`);
  }

  for (const [key, value] of Object.entries(theme.shadows)) {
    variables.push(`--shadow-${key}: ${value};`);
  }

  variables.push(`--duration-fast: ${theme.animations.durationFast};`);
  variables.push(`--duration-normal: ${theme.animations.durationNormal};`);
  variables.push(`--duration-slow: ${theme.animations.durationSlow};`);
  variables.push(`--easing: ${theme.animations.easing};`);
  variables.push(`--easing-bounce: ${theme.animations.easingBounce};`);

  if (theme.components) {
    const { chatBubble, header, input, widget } = theme.components;

    if (chatBubble) {
      if (chatBubble.borderRadius) variables.push(`--bubble-radius: ${chatBubble.borderRadius};`);
      if (chatBubble.padding) variables.push(`--bubble-padding: ${chatBubble.padding};`);
      if (chatBubble.maxWidth) variables.push(`--bubble-max-width: ${chatBubble.maxWidth};`);
      if (chatBubble.shadow) variables.push(`--bubble-shadow: ${chatBubble.shadow};`);
    }

    if (header) {
      if (header.height) variables.push(`--header-height: ${header.height};`);
      if (header.padding) variables.push(`--header-padding: ${header.padding};`);
      if (header.background) variables.push(`--header-bg: ${header.background};`);
    }

    if (input) {
      if (input.height) variables.push(`--input-height: ${input.height};`);
      if (input.padding) variables.push(`--input-padding: ${input.padding};`);
      if (input.borderRadius) variables.push(`--input-radius: ${input.borderRadius};`);
    }

    if (widget) {
      if (widget.width) variables.push(`--widget-width: ${widget.width};`);
      if (widget.height) variables.push(`--widget-height: ${widget.height};`);
      if (widget.borderRadius) variables.push(`--widget-radius: ${widget.borderRadius};`);
      if (widget.shadow) variables.push(`--widget-shadow: ${widget.shadow};`);
      if (widget.position?.bottom) variables.push(`--widget-bottom: ${widget.position.bottom};`);
      if (widget.position?.right) variables.push(`--widget-right: ${widget.position.right};`);
      if (widget.position?.left) variables.push(`--widget-left: ${widget.position.left};`);
    }
  }

  return variables.join('\n');
}

export function injectThemeCSS(theme: ThemeConfig): void {
  const cssVariables = generateCSSVariables(theme);

  let styleElement = document.getElementById('chatbot-theme-vars');
  if (!styleElement) {
    styleElement = document.createElement('style');
    styleElement.id = 'chatbot-theme-vars';
    document.head.appendChild(styleElement);
  }

  styleElement.textContent = `:root {\n${cssVariables}\n}`;

  if (theme.customCSS) {
    let customStyleElement = document.getElementById('chatbot-custom-css');
    if (!customStyleElement) {
      customStyleElement = document.createElement('style');
      customStyleElement.id = 'chatbot-custom-css';
      document.head.appendChild(customStyleElement);
    }
    customStyleElement.textContent = theme.customCSS;
  }
}

interface ThemeProviderProps {
  children: ReactNode;
  initialTheme?: ThemeConfig;
  themeUrl?: string;
}

/** Trae un tema de una URL, lo funde con el de por defecto y lo valida.
 *
 * Fuera del componente y sin tocar estado: asi la usan **los dos** consumidores —`loadTheme`,
 * que es API del contexto, y el efecto que reacciona a `themeUrl`— sin duplicar el cuerpo ni
 * obligar al efecto a llamar a un `setState` sincrono.
 *
 * Lanza si la respuesta no es 200; quien llama decide que hacer con el fallo.
 */
async function traerTema(url: string): Promise<{ tema: ThemeConfig; avisos: string[] }> {
  const respuesta = await fetch(url);
  if (!respuesta.ok) {
    throw new Error(`Failed to load theme: ${respuesta.statusText}`);
  }
  const parcial = await respuesta.json();
  const fundido = mergeThemes(DEFAULT_THEME, parcial);
  const validacion = validateTheme(fundido);
  return { tema: fundido, avisos: [...validacion.errors, ...validacion.warnings] };
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({
  children,
  initialTheme,
  themeUrl,
}) => {
  const [theme, setThemeState] = useState<ThemeConfig>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        return mergeThemes(DEFAULT_THEME, parsed);
      }
    } catch {
      // ignore parse errors
    }
    return initialTheme || DEFAULT_THEME;
  });

  // Nace en `true` cuando hay un tema que traer. Antes nacia en `false` y el efecto lo subia
  // despues, asi que el primer render decia «no estoy cargando» mientras iba a descargar — un
  // parpadeo, y ademas el `setState` sincrono dentro del efecto que el linter senala.
  const [isLoading, setIsLoading] = useState(Boolean(themeUrl));
  const [error, setError] = useState<Error | null>(null);
  const [validationWarnings, setValidationWarnings] = useState<string[]>([]);

  useEffect(() => {
    injectThemeCSS(theme);
  }, [theme]);

  const setTheme = useCallback((newTheme: ThemeConfig) => {
    const validation = validateTheme(newTheme);
    if (!validation.valid) {
      console.warn('Theme validation failed:', validation.errors);
    }
    setValidationWarnings(validation.warnings);
    setThemeState(newTheme);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newTheme));
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
      // Fall back to default on network/HTTP error
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
    localStorage.removeItem(STORAGE_KEY);
  }, [setTheme]);

  // El tema que llega por `themeUrl`. Llamaba a `loadTheme`, que hace `setIsLoading(true)` de
  // forma sincrona: de ahi el aviso del linter. Pero el defecto de verdad era otro y no lo
  // senalaba nadie: **no habia cancelacion**. Si `themeUrl` cambiaba, las dos descargas
  // competian y ganaba la que tardara mas, dejando aplicado el tema equivocado.
  useEffect(() => {
    if (!themeUrl) return;
    let vigente = true;

    traerTema(themeUrl)
      .then(({ tema, avisos }) => {
        if (!vigente) return;
        setValidationWarnings(avisos);
        setThemeState(tema);
      })
      .catch((e: unknown) => {
        if (!vigente) return;
        const err = e instanceof Error ? e : new Error('Unknown error loading theme');
        setError(err);
        setThemeState(DEFAULT_THEME);
        console.error('Failed to load theme:', err);
      })
      .finally(() => {
        if (vigente) setIsLoading(false);
      });

    return () => {
      vigente = false;
    };
  }, [themeUrl]);

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

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

export function withTheme<P extends object>(
  Component: React.ComponentType<P & { theme: ThemeConfig }>
): React.FC<Omit<P, 'theme'>> {
  return function ThemedComponent(props: Omit<P, 'theme'>) {
    const { theme } = useTheme();
    return <Component {...(props as P)} theme={theme} />;
  };
}
