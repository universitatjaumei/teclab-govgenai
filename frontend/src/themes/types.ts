export interface ThemeColors {
  primary: string;
  primaryHover: string;
  primaryLight: string;
  secondary: string;
  secondaryHover: string;

  background: string;
  surface: string;
  surfaceHover: string;

  text: string;
  textSecondary: string;
  textMuted: string;
  textOnPrimary: string;

  border: string;
  borderLight: string;
  divider: string;

  error: string;
  errorLight: string;
  success: string;
  successLight: string;
  warning: string;
  warningLight: string;
  info: string;
  infoLight: string;

  botMessage: string;
  botMessageText: string;
  userMessage: string;
  userMessageText: string;

  overlay: string;
  shadow: string;
}

export interface ThemeTypography {
  fontFamily: string;
  fontFamilyMono: string;

  fontSizeXs: string;
  fontSizeSmall: string;
  fontSize: string;
  fontSizeMd: string;
  fontSizeLarge: string;
  fontSizeXl: string;
  fontSizeXxl: string;

  fontWeightLight: number;
  fontWeight: number;
  fontWeightMedium: number;
  fontWeightBold: number;

  lineHeight: number;
  lineHeightTight: number;
  lineHeightRelaxed: number;

  letterSpacing: string;
  letterSpacingWide: string;
}

export interface ThemeSpacing {
  xs: string;
  sm: string;
  md: string;
  lg: string;
  xl: string;
  xxl: string;
}

export interface ThemeBorderRadius {
  none: string;
  sm: string;
  md: string;
  lg: string;
  xl: string;
  full: string;
}

export interface ThemeShadows {
  none: string;
  sm: string;
  md: string;
  lg: string;
  xl: string;
}

export interface ChatBubbleStyles {
  borderRadius?: string;
  padding?: string;
  maxWidth?: string;
  shadow?: string;
}

export interface HeaderStyles {
  height?: string;
  padding?: string;
  background?: string;
  borderBottom?: string;
}

export interface InputStyles {
  height?: string;
  padding?: string;
  borderRadius?: string;
  border?: string;
  focusBorder?: string;
}

export interface ButtonStyles {
  padding?: string;
  borderRadius?: string;
  fontWeight?: number;
  textTransform?: 'none' | 'uppercase' | 'capitalize';
}

export interface WidgetStyles {
  width?: string;
  height?: string;
  borderRadius?: string;
  shadow?: string;
  position?: {
    bottom?: string;
    right?: string;
    left?: string;
  };
}

export interface ThemeComponents {
  chatBubble?: ChatBubbleStyles;
  header?: HeaderStyles;
  input?: InputStyles;
  button?: ButtonStyles;
  widget?: WidgetStyles;
}

export interface ThemeAnimations {
  durationFast: string;
  durationNormal: string;
  durationSlow: string;
  easing: string;
  easingBounce: string;
}

/** La marca de la institución, que llega por la cascada y no por un `import`.
 *
 * `AppLayout` importaba `@/assets/logo-uji.png`: una imagen importada desde `src/` se
 * compila dentro del bundle, así que era la misma para todos los despliegues de un
 * proyecto pensado para servir a varias administraciones. Lo vigila
 * `src/__tests__/marcaNoViajaEnElRepo.test.ts`.
 */
export interface ThemeBranding {
  logoUrl?: string;
  logoAlt?: string;
  /** Lo deduce el servidor de la firma real del fichero; el cliente no lo necesita. */
  logoContentType?: string;
}

export interface ThemeConfig {
  name: string;
  version: string;
  branding?: ThemeBranding;
  colors: ThemeColors;
  typography: ThemeTypography;
  spacing: ThemeSpacing;
  borderRadius: ThemeBorderRadius;
  shadows: ThemeShadows;
  animations: ThemeAnimations;
  components?: ThemeComponents;
  customCSS?: string;
}

export const DEFAULT_THEME: ThemeConfig = {
  name: 'default',
  version: '1.0.0',

  colors: {
    primary: '#0066cc',
    primaryHover: '#0052a3',
    primaryLight: '#e6f0fa',
    secondary: '#6c757d',
    secondaryHover: '#545b62',

    background: '#ffffff',
    surface: '#f8f9fa',
    surfaceHover: '#e9ecef',

    text: '#212529',
    textSecondary: '#6c757d',
    textMuted: '#adb5bd',
    textOnPrimary: '#ffffff',

    border: '#dee2e6',
    borderLight: '#e9ecef',
    divider: '#e9ecef',

    error: '#dc3545',
    errorLight: '#f8d7da',
    success: '#28a745',
    successLight: '#d4edda',
    warning: '#ffc107',
    warningLight: '#fff3cd',
    info: '#17a2b8',
    infoLight: '#d1ecf1',

    botMessage: '#f1f3f4',
    botMessageText: '#212529',
    userMessage: '#0066cc',
    userMessageText: '#ffffff',

    overlay: 'rgba(0, 0, 0, 0.5)',
    shadow: 'rgba(0, 0, 0, 0.1)',
  },

  typography: {
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontFamilyMono: "'Fira Code', 'Consolas', monospace",

    fontSizeXs: '0.75rem',
    fontSizeSmall: '0.875rem',
    fontSize: '1rem',
    fontSizeMd: '1rem',
    fontSizeLarge: '1.125rem',
    fontSizeXl: '1.25rem',
    fontSizeXxl: '1.5rem',

    fontWeightLight: 300,
    fontWeight: 400,
    fontWeightMedium: 500,
    fontWeightBold: 600,

    lineHeight: 1.5,
    lineHeightTight: 1.25,
    lineHeightRelaxed: 1.75,

    letterSpacing: 'normal',
    letterSpacingWide: '0.025em',
  },

  spacing: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
    xxl: '3rem',
  },

  borderRadius: {
    none: '0',
    sm: '0.25rem',
    md: '0.5rem',
    lg: '0.75rem',
    xl: '1rem',
    full: '9999px',
  },

  shadows: {
    none: 'none',
    sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px rgba(0, 0, 0, 0.1)',
    lg: '0 10px 15px rgba(0, 0, 0, 0.1)',
    xl: '0 20px 25px rgba(0, 0, 0, 0.15)',
  },

  animations: {
    durationFast: '150ms',
    durationNormal: '300ms',
    durationSlow: '500ms',
    easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
    easingBounce: 'cubic-bezier(0.68, -0.55, 0.265, 1.55)',
  },

  components: {
    chatBubble: {
      borderRadius: '1rem',
      padding: '0.75rem 1rem',
      maxWidth: '80%',
      shadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
    },
    header: {
      height: '60px',
      padding: '0 1rem',
      background: 'linear-gradient(135deg, #0066cc 0%, #0052a3 100%)',
      borderBottom: 'none',
    },
    input: {
      height: '48px',
      padding: '0.75rem 1rem',
      borderRadius: '24px',
      border: '1px solid #dee2e6',
      focusBorder: '2px solid #0066cc',
    },
    button: {
      padding: '0.5rem 1rem',
      borderRadius: '0.5rem',
      fontWeight: 500,
      textTransform: 'none',
    },
    widget: {
      width: '380px',
      height: '600px',
      borderRadius: '1rem',
      shadow: '0 10px 40px rgba(0, 0, 0, 0.15)',
      position: {
        bottom: '20px',
        right: '20px',
      },
    },
  },
};

const COLOR_REGEX = /^(#[0-9a-fA-F]{3,8}|rgb\(|rgba\(|hsl\(|hsla\(|[a-z]+$)/;

const REQUIRED_COLORS: (keyof ThemeColors)[] = [
  'primary',
  'secondary',
  'background',
  'surface',
  'text',
  'textSecondary',
  'border',
  'error',
  'success',
  'warning',
  'botMessage',
  'userMessage',
  'botMessageText',
  'userMessageText',
];

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export function validateTheme(theme: ThemeConfig): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  for (const colorKey of REQUIRED_COLORS) {
    if (!theme.colors[colorKey]) {
      errors.push(`Missing required color: ${colorKey}`);
    }
  }

  for (const [key, value] of Object.entries(theme.colors)) {
    if (value && !COLOR_REGEX.test(value)) {
      errors.push(`Invalid color format for ${key}: ${value}`);
    }
  }

  if (!theme.typography.fontFamily) {
    errors.push('Missing required typography.fontFamily');
  }

  if (!theme.typography.fontSize) {
    errors.push('Missing required typography.fontSize');
  }

  const requiredSpacing = ['xs', 'sm', 'md', 'lg', 'xl'];
  for (const key of requiredSpacing) {
    if (!theme.spacing[key as keyof ThemeSpacing]) {
      errors.push(`Missing required spacing: ${key}`);
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

export function mergeThemes(
  base: ThemeConfig,
  partial: DeepPartial<ThemeConfig>
): ThemeConfig {
  return deepMerge(base, partial) as ThemeConfig;
}

function deepMerge<T extends object>(target: T, source: DeepPartial<T>): T {
  const result = { ...target };

  for (const key in source) {
    if (source[key] !== undefined) {
      if (
        typeof source[key] === 'object' &&
        source[key] !== null &&
        !Array.isArray(source[key])
      ) {
        result[key] = deepMerge(
          target[key] as object,
          source[key] as DeepPartial<object>
        ) as T[Extract<keyof T, string>];
      } else {
        result[key] = source[key] as T[Extract<keyof T, string>];
      }
    }
  }

  return result;
}

/** Dónde se recuerda el tema elegido en este navegador. El cierre de sesión lo olvida (#278). */
export const CLAVE_DEL_TEMA = 'chatbot-theme'
