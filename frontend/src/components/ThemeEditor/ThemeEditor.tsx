import React, { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../themes/ThemeProvider';
import { DEFAULT_THEME, validateTheme, type ThemeConfig } from '../../themes/types';
import { THEME_PRESETS, type ThemePresetName } from '../../themes/presets';
import styles from './ThemeEditor.module.css';

interface ColorInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

const ColorInput: React.FC<ColorInputProps> = ({ label, value, onChange }) => (
  <div className={styles.colorInput}>
    <label className={styles.colorLabel}>{label}</label>
    <div className={styles.colorInputWrapper}>
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={styles.colorPicker}
      />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={styles.colorText}
        pattern="^#[0-9a-fA-F]{6}$"
      />
    </div>
  </div>
);

interface ThemeEditorProps {
  onSave?: (theme: ThemeConfig) => Promise<void>;
  onCancel?: () => void;
}

export const ThemeEditor: React.FC<ThemeEditorProps> = ({ onSave, onCancel }) => {
  const { t } = useTranslation();
  const { theme, setTheme, availableThemes } = useTheme();
  const [localTheme, setLocalTheme] = useState<ThemeConfig>(theme);
  const [activeTab, setActiveTab] = useState<'colors' | 'typography' | 'components' | 'preview'>('colors');
  const [isSaving, setIsSaving] = useState(false);

  // El borrador se reinicia cuando cambia el tema global —alguien cambia de preset y el editor
  // tiene que mostrarlo—. Va **durante el render** y no en un efecto, que es el patron que React
  // documenta para «ajustar estado cuando cambia una prop»: con el efecto, React pintaba un
  // fotograma con el borrador viejo antes de corregirlo.
  const [temaPrevio, setTemaPrevio] = useState<ThemeConfig>(theme);
  if (theme !== temaPrevio) {
    setTemaPrevio(theme);
    setLocalTheme(theme);
  }

  // Los errores de validacion son estado **derivado** de `localTheme`, no estado propio: se leen
  // para pintarlos y para bloquear el guardado, y nadie los escribe por otra via. Con
  // efecto + `useState` cada tecleo costaba un render de mas —el del borrador y el de los
  // errores—, y durante ese hueco `validationErrors` describia el borrador ANTERIOR: pulsar
  // «Guardar» justo ahi podia dejar pasar un tema invalido o bloquear uno valido.
  const validationErrors = useMemo(() => validateTheme(localTheme).errors, [localTheme]);

  const updateColor = useCallback((key: keyof ThemeConfig['colors'], value: string) => {
    setLocalTheme((prev) => ({
      ...prev,
      colors: { ...prev.colors, [key]: value },
    }));
  }, []);

  const updateTypography = useCallback(
    (key: keyof ThemeConfig['typography'], value: string | number) => {
      setLocalTheme((prev) => ({
        ...prev,
        typography: { ...prev.typography, [key]: value },
      }));
    },
    []
  );

  const applyPreset = useCallback((presetName: string) => {
    const preset = THEME_PRESETS[presetName as ThemePresetName];
    if (preset) {
      setLocalTheme(preset);
    }
  }, []);

  const handlePreview = useCallback(() => {
    setTheme(localTheme);
  }, [localTheme, setTheme]);

  const handleSave = useCallback(async () => {
    if (validationErrors.length > 0) return;
    setIsSaving(true);
    try {
      setTheme(localTheme);
      if (onSave) await onSave(localTheme);
    } finally {
      setIsSaving(false);
    }
  }, [localTheme, validationErrors, setTheme, onSave]);

  const handleReset = useCallback(() => {
    setLocalTheme(DEFAULT_THEME);
    setTheme(DEFAULT_THEME);
  }, [setTheme]);

  const handleExport = useCallback(() => {
    const json = JSON.stringify(localTheme, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `theme-${localTheme.name}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [localTheme]);

  const handleImport = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const imported = JSON.parse(e.target?.result as string);
        setLocalTheme({ ...DEFAULT_THEME, ...imported });
      } catch (err) {
        console.error('Failed to parse theme file:', err);
      }
    };
    reader.readAsText(file);
  }, []);

  return (
    <div className={styles.editor}>
      <div className={styles.header}>
        <h2 className={styles.title}>{t('themeEditor.title', 'Editor de Tema')}</h2>
        <div className={styles.presetSelector}>
          <label>{t('themeEditor.preset', 'Preset')}:</label>
          <select
            value={localTheme.name}
            onChange={(e) => applyPreset(e.target.value)}
            className={styles.select}
          >
            {availableThemes.map((name) => (
              <option key={name} value={name}>
                {name.charAt(0).toUpperCase() + name.slice(1)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className={styles.tabs}>
        {(['colors', 'typography', 'components', 'preview'] as const).map((tab) => (
          <button
            key={tab}
            className={`${styles.tab} ${activeTab === tab ? styles.active : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {t(`themeEditor.${tab}`, tab.charAt(0).toUpperCase() + tab.slice(1))}
          </button>
        ))}
      </div>

      <div className={styles.content}>
        {activeTab === 'colors' && (
          <div className={styles.colorGrid}>
            <h3>{t('themeEditor.mainColors', 'Colores Principales')}</h3>
            <ColorInput label="Primary" value={localTheme.colors.primary} onChange={(v) => updateColor('primary', v)} />
            <ColorInput label="Primary Hover" value={localTheme.colors.primaryHover} onChange={(v) => updateColor('primaryHover', v)} />
            <ColorInput label="Secondary" value={localTheme.colors.secondary} onChange={(v) => updateColor('secondary', v)} />

            <h3>{t('themeEditor.backgrounds', 'Fondos')}</h3>
            <ColorInput label="Background" value={localTheme.colors.background} onChange={(v) => updateColor('background', v)} />
            <ColorInput label="Surface" value={localTheme.colors.surface} onChange={(v) => updateColor('surface', v)} />

            <h3>{t('themeEditor.text', 'Texto')}</h3>
            <ColorInput label="Text" value={localTheme.colors.text} onChange={(v) => updateColor('text', v)} />
            <ColorInput label="Text Secondary" value={localTheme.colors.textSecondary} onChange={(v) => updateColor('textSecondary', v)} />

            <h3>{t('themeEditor.chatMessages', 'Mensajes del Chat')}</h3>
            <ColorInput label="Bot Message BG" value={localTheme.colors.botMessage} onChange={(v) => updateColor('botMessage', v)} />
            <ColorInput label="Bot Message Text" value={localTheme.colors.botMessageText} onChange={(v) => updateColor('botMessageText', v)} />
            <ColorInput label="User Message BG" value={localTheme.colors.userMessage} onChange={(v) => updateColor('userMessage', v)} />
            <ColorInput label="User Message Text" value={localTheme.colors.userMessageText} onChange={(v) => updateColor('userMessageText', v)} />
          </div>
        )}

        {activeTab === 'typography' && (
          <div className={styles.typographyPanel}>
            <div className={styles.inputGroup}>
              <label>{t('themeEditor.fontFamily', 'Familia de fuente')}</label>
              <input
                type="text"
                value={localTheme.typography.fontFamily}
                onChange={(e) => updateTypography('fontFamily', e.target.value)}
                className={styles.textInput}
              />
            </div>
            <div className={styles.inputGroup}>
              <label>{t('themeEditor.fontSize', 'Tamaño base')}</label>
              <input
                type="text"
                value={localTheme.typography.fontSize}
                onChange={(e) => updateTypography('fontSize', e.target.value)}
                className={styles.textInput}
              />
            </div>
            <div className={styles.inputGroup}>
              <label>{t('themeEditor.lineHeight', 'Altura de línea')}</label>
              <input
                type="number"
                step="0.1"
                value={localTheme.typography.lineHeight}
                onChange={(e) => updateTypography('lineHeight', parseFloat(e.target.value))}
                className={styles.textInput}
              />
            </div>
          </div>
        )}

        {activeTab === 'preview' && (
          <div className={styles.previewPanel}>
            <p>{t('themeEditor.previewDescription', 'Vista previa del tema aplicado al widget.')}</p>
            <div
              className={styles.miniPreview}
              style={{
                backgroundColor: localTheme.colors.background,
                color: localTheme.colors.text,
                fontFamily: localTheme.typography.fontFamily,
              }}
            >
              <div style={{ backgroundColor: localTheme.colors.primary, color: localTheme.colors.textOnPrimary, padding: '1rem' }}>
                Header del Chat
              </div>
              <div style={{ padding: '1rem' }}>
                <div style={{ backgroundColor: localTheme.colors.botMessage, color: localTheme.colors.botMessageText, padding: '0.5rem 1rem', borderRadius: '1rem', marginBottom: '0.5rem', maxWidth: '80%' }}>
                  ¡Hola! ¿En qué puedo ayudarte?
                </div>
                <div style={{ backgroundColor: localTheme.colors.userMessage, color: localTheme.colors.userMessageText, padding: '0.5rem 1rem', borderRadius: '1rem', marginLeft: 'auto', maxWidth: '80%' }}>
                  Tengo una pregunta sobre...
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {validationErrors.length > 0 && (
        <div className={styles.errors}>
          {validationErrors.map((error, i) => (
            <div key={i} className={styles.error}>⚠️ {error}</div>
          ))}
        </div>
      )}

      <div className={styles.actions}>
        <div className={styles.leftActions}>
          <button onClick={handlePreview} className={styles.btnSecondary}>
            {t('themeEditor.preview', 'Vista Previa')}
          </button>
          <button onClick={handleReset} className={styles.btnSecondary}>
            {t('themeEditor.reset', 'Resetear')}
          </button>
        </div>
        <div className={styles.rightActions}>
          <button onClick={handleExport} className={styles.btnSecondary}>
            {t('themeEditor.export', 'Exportar')}
          </button>
          <label className={styles.btnSecondary}>
            {t('themeEditor.import', 'Importar')}
            <input type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
          </label>
          {onCancel && (
            <button onClick={onCancel} className={styles.btnSecondary}>
              {t('common.cancel', 'Cancelar')}
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={validationErrors.length > 0 || isSaving}
            className={styles.btnPrimary}
          >
            {isSaving ? t('common.saving', 'Guardando...') : t('common.save', 'Guardar')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ThemeEditor;
