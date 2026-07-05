import { Plus, RefreshCw, RotateCcw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { API_BASE_URL, fetchConfigStatus, fetchSettings, resetSettings, saveSettings } from "../api";
import type { Language, Translation } from "../i18n";
import type { ConfigStatus, RunDailyParams, UiSettings } from "../types";

type SettingsPageProps = {
  t: Translation;
  language: Language;
  runParams: RunDailyParams;
  settings: UiSettings | null;
  onSettingsChange: (settings: UiSettings) => void;
};

const fallbackSettings: UiSettings = {
  run_defaults: {
    limit_per_keyword: 3,
    score_top: 30,
    research_top: 3,
    article_top: 3,
    review_threshold: 80,
    cooldown_days: 30,
    ignore_history: false,
    allow_recent_fallback: false,
    prefer_growth_projects: true,
  },
  discovery: {
    daily_keywords: ["ai agent", "llm agent", "mcp", "rag", "multi-agent", "workflow automation"],
  },
  frontend: {
    default_language: "zh",
  },
};

type NumericRunParam = Exclude<keyof RunDailyParams, "ignore_history" | "allow_recent_fallback" | "prefer_growth_projects">;

const runParamFields: Array<[NumericRunParam, number, number]> = [
  ["limit_per_keyword", 1, 50],
  ["score_top", 1, 100],
  ["research_top", 1, 20],
  ["article_top", 1, 20],
  ["review_threshold", 0, 100],
  ["cooldown_days", 0, 365],
];

export function SettingsPage({ t, language, runParams, settings, onSettingsChange }: SettingsPageProps) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [draft, setDraft] = useState<UiSettings>(settings || { ...fallbackSettings, run_defaults: runParams });
  const [newKeyword, setNewKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refreshAll = () => {
    setLoading(true);
    setError("");
    Promise.all([fetchConfigStatus(), fetchSettings()])
      .then(([configPayload, settingsPayload]) => {
        setConfig(configPayload);
        setDraft(settingsPayload.settings);
        onSettingsChange(settingsPayload.settings);
        setMessage("");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : t.messages.configSaveFailed);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchConfigStatus(), fetchSettings()])
      .then(([configPayload, settingsPayload]) => {
        if (!cancelled) {
          setConfig(configPayload);
          setDraft(settingsPayload.settings);
          onSettingsChange(settingsPayload.settings);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load config status");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [onSettingsChange]);

  const statusText = (configured?: boolean) => (configured ? t.labels.configured : t.labels.notConfigured);

  const updateRunDefault = (name: NumericRunParam, value: string) => {
    const numericValue = Number(value);
    setDraft((current) => ({
      ...current,
      run_defaults: {
        ...current.run_defaults,
        [name]: Number.isFinite(numericValue) ? numericValue : current.run_defaults[name],
      },
    }));
  };

  const updateIgnoreHistory = (value: boolean) => {
    setDraft((current) => ({
      ...current,
      run_defaults: {
        ...current.run_defaults,
        ignore_history: value,
      },
    }));
  };

  const updateAllowRecentFallback = (value: boolean) => {
    setDraft((current) => ({
      ...current,
      run_defaults: {
        ...current.run_defaults,
        allow_recent_fallback: value,
      },
    }));
  };

  const updatePreferGrowthProjects = (value: boolean) => {
    setDraft((current) => ({
      ...current,
      run_defaults: {
        ...current.run_defaults,
        prefer_growth_projects: value,
      },
    }));
  };

  const updateKeyword = (index: number, value: string) => {
    setDraft((current) => ({
      ...current,
      discovery: {
        daily_keywords: current.discovery.daily_keywords.map((keyword, keywordIndex) =>
          keywordIndex === index ? value : keyword,
        ),
      },
    }));
  };

  const addKeyword = () => {
    const keyword = newKeyword.trim();
    if (!keyword) return;
    setDraft((current) => ({
      ...current,
      discovery: {
        daily_keywords: [...current.discovery.daily_keywords, keyword],
      },
    }));
    setNewKeyword("");
  };

  const removeKeyword = (index: number) => {
    setDraft((current) => ({
      ...current,
      discovery: {
        daily_keywords: current.discovery.daily_keywords.filter((_, keywordIndex) => keywordIndex !== index),
      },
    }));
  };

  const restoreDefaultKeywords = () => {
    setDraft((current) => ({
      ...current,
      discovery: { daily_keywords: [...fallbackSettings.discovery.daily_keywords] },
    }));
  };

  const changeDefaultLanguage = (value: Language) => {
    setDraft((current) => ({
      ...current,
      frontend: { default_language: value },
    }));
  };

  const persistSettings = async () => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const payload = await saveSettings(draft);
      setDraft(payload.settings);
      onSettingsChange(payload.settings);
      setMessage(t.messages.configSaved);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.messages.configSaveFailed);
    } finally {
      setSaving(false);
    }
  };

  const resetToDefaults = async () => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const payload = await resetSettings();
      setDraft(payload.settings);
      onSettingsChange(payload.settings);
      setMessage(t.messages.configSaved);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.messages.configSaveFailed);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-stack">
      <section className="panel page-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.pageTitles.settings}</h2>
            <p>{t.pageSubtitles.settings}</p>
          </div>
          <div className="row-actions wrap-actions">
            <button className="secondary-button" type="button" onClick={refreshAll} disabled={loading || saving}>
              <RefreshCw size={16} aria-hidden="true" />
              <span>{t.actions.refresh}</span>
            </button>
            <button className="secondary-button" type="button" onClick={resetToDefaults} disabled={loading || saving}>
              <RotateCcw size={16} aria-hidden="true" />
              <span>{t.actions.resetDefaults}</span>
            </button>
            <button className="primary-button" type="button" onClick={() => void persistSettings()} disabled={loading || saving}>
              <Save size={16} aria-hidden="true" />
              <span>{saving ? t.actions.saving : t.actions.saveSettings}</span>
            </button>
          </div>
        </div>

        {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}
        {message ? <div className="banner success">{message}</div> : null}

        <div className="settings-grid">
          <section className="detail-section">
            <h3>{t.sections.settingsStatus}</h3>
            <div className="settings-list">
              <div><span>{t.labels.githubToken}</span><strong>{statusText(config?.github_token_configured)}</strong></div>
              <div><span>{t.labels.llm}</span><strong>{statusText(config?.llm_configured)}</strong></div>
              <div><span>{t.labels.workspaceDir}</span><strong>{config?.workspace_dir || "-"}</strong></div>
              <div><span>{t.labels.outputDir}</span><strong>{config?.output_dir || "-"}</strong></div>
              <div><span>{t.labels.apiBaseUrl}</span><strong>{API_BASE_URL}</strong></div>
              <div><span>{t.labels.frontendLanguage}</span><strong>{language === "zh" ? "中文" : "English"}</strong></div>
            </div>
          </section>

          <section className="detail-section">
            <h3>{t.sections.defaultRunParams}</h3>
            <div className="settings-form-grid">
              {runParamFields.map(([name, min, max]) => (
                <label key={name}>
                  <span>{name === "cooldown_days" ? t.settings.cooldownDays : name}</span>
                  <input
                    type="number"
                    min={min}
                    max={max}
                    step="1"
                    value={draft.run_defaults[name]}
                    onChange={(event) => updateRunDefault(name, event.target.value)}
                    disabled={loading || saving}
                  />
                </label>
              ))}
              <label className="checkbox-setting">
                <span>{t.settings.ignoreHistory}</span>
                <input
                  type="checkbox"
                  checked={draft.run_defaults.ignore_history}
                  onChange={(event) => updateIgnoreHistory(event.target.checked)}
                  disabled={loading || saving}
                />
              </label>
              <label className="checkbox-setting">
                <span>{t.settings.allowRecentFallback}</span>
                <input
                  type="checkbox"
                  checked={draft.run_defaults.allow_recent_fallback}
                  onChange={(event) => updateAllowRecentFallback(event.target.checked)}
                  disabled={loading || saving}
                />
              </label>
              <label className="checkbox-setting">
                <span>{t.settings.preferGrowthProjects}</span>
                <input
                  type="checkbox"
                  checked={draft.run_defaults.prefer_growth_projects}
                  onChange={(event) => updatePreferGrowthProjects(event.target.checked)}
                  disabled={loading || saving}
                />
              </label>
            </div>
            <p className="detail-note">{t.settings.preferNewProjects}</p>
          </section>

          <section className="detail-section">
            <div className="section-title-row">
              <h3>{t.sections.keywordManagement}</h3>
              <button className="secondary-button compact-button" type="button" onClick={restoreDefaultKeywords} disabled={loading || saving}>
                <RotateCcw size={15} aria-hidden="true" />
                <span>{t.actions.restoreDefaultKeywords}</span>
              </button>
            </div>
            <div className="keyword-editor">
              {draft.discovery.daily_keywords.map((keyword, index) => (
                <div className="keyword-row" key={`${keyword}-${index}`}>
                  <input
                    value={keyword}
                    maxLength={80}
                    onChange={(event) => updateKeyword(index, event.target.value)}
                    disabled={loading || saving}
                    aria-label={`${t.labels.dailyKeywords} ${index + 1}`}
                  />
                  <button
                    className="icon-button"
                    type="button"
                    onClick={() => removeKeyword(index)}
                    disabled={loading || saving || draft.discovery.daily_keywords.length <= 1}
                    title={t.actions.delete}
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
              <div className="keyword-row">
                <input
                  value={newKeyword}
                  maxLength={80}
                  placeholder={t.actions.addKeyword}
                  onChange={(event) => setNewKeyword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addKeyword();
                    }
                  }}
                  disabled={loading || saving || draft.discovery.daily_keywords.length >= 30}
                />
                <button className="icon-button" type="button" onClick={addKeyword} disabled={loading || saving || draft.discovery.daily_keywords.length >= 30}>
                  <Plus size={16} aria-hidden="true" />
                </button>
              </div>
            </div>
          </section>

          <section className="detail-section">
            <h3>{t.sections.frontendPreferences}</h3>
            <label className="settings-select">
              <span>{t.labels.defaultLanguage}</span>
              <select
                value={draft.frontend.default_language}
                onChange={(event) => changeDefaultLanguage(event.target.value as Language)}
                disabled={loading || saving}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </label>
          </section>

          <section className="detail-section safety-section">
            <h3>{t.sections.safetyNotice}</h3>
            <p><ShieldCheck size={17} aria-hidden="true" /> {t.settings.tokenNotice}</p>
            <p>{t.settings.secretStorageNotice}</p>
          </section>
        </div>
      </section>
    </div>
  );
}
