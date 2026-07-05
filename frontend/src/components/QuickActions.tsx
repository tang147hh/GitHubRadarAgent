import { Clipboard, Copy, FileText, Play, SlidersHorizontal } from "lucide-react";
import type { Translation } from "../i18n";
import type { RunDailyParams } from "../types";

type QuickActionsProps = {
  t: Translation;
  params: RunDailyParams;
  onParamsChange: (params: RunDailyParams) => void;
  onRunDaily: () => void;
  onOpenFinalArticles: () => void;
  onViewScoreReport: () => void;
  onCopyLatestMarkdown: () => void;
  isRunning?: boolean;
  disabled?: boolean;
  message?: string;
};

type NumericRunParam = Exclude<keyof RunDailyParams, "ignore_history" | "allow_recent_fallback" | "prefer_growth_projects">;

export function QuickActions({
  t,
  params,
  onParamsChange,
  onRunDaily,
  onOpenFinalArticles,
  onViewScoreReport,
  onCopyLatestMarkdown,
  isRunning = false,
  disabled = false,
  message,
}: QuickActionsProps) {
  const actions = [
    { label: isRunning ? t.actions.running : t.actions.runDaily, icon: Play, primary: true, onClick: onRunDaily, disabled: disabled || isRunning },
    { label: t.actions.openFinalArticles, icon: FileText, onClick: onOpenFinalArticles },
    { label: t.actions.viewScoreReport, icon: Clipboard, onClick: onViewScoreReport },
    { label: t.actions.copyLatestMarkdown, icon: Copy, onClick: onCopyLatestMarkdown },
  ];

  const parameters: Array<[NumericRunParam, number, number]> = [
    ["limit_per_keyword", 1, 50],
    ["score_top", 1, 100],
    ["research_top", 1, 20],
    ["article_top", 1, 20],
    ["review_threshold", 0, 100],
    ["cooldown_days", 0, 365],
  ];

  const updateParam = (name: NumericRunParam, value: string) => {
    const numericValue = Number(value);
    onParamsChange({
      ...params,
      [name]: Number.isFinite(numericValue) ? numericValue : params[name],
    });
  };

  const updateIgnoreHistory = (value: boolean) => {
    onParamsChange({
      ...params,
      ignore_history: value,
    });
  };

  const updateAllowRecentFallback = (value: boolean) => {
    onParamsChange({
      ...params,
      allow_recent_fallback: value,
    });
  };

  const updatePreferGrowthProjects = (value: boolean) => {
    onParamsChange({
      ...params,
      prefer_growth_projects: value,
    });
  };

  return (
    <section className="panel quick-actions-panel">
      <div className="panel-header">
        <h2>{t.sections.quickActions}</h2>
        <SlidersHorizontal size={18} aria-hidden="true" />
      </div>

      <div className="quick-actions-grid">
        <div className="action-stack">
          {actions.map((action) => {
            const Icon = action.icon;
            return (
              <button
                className={action.primary ? "primary-button full" : "secondary-button full"}
                type="button"
                key={action.label}
                onClick={action.onClick}
                disabled={action.disabled}
              >
                <Icon className={isRunning && action.primary ? "spin-icon" : ""} size={17} aria-hidden="true" />
                <span>{action.label}</span>
              </button>
            );
          })}
          {message ? <p className="action-message">{message}</p> : null}
        </div>

        <form className="parameter-form">
          <h3>{t.sections.runParameters}</h3>
          {parameters.map(([name, min, max]) => (
            <label key={name}>
              <span>{name === "cooldown_days" ? t.settings.cooldownDays : name}</span>
              <input
                type="number"
                min={min}
                max={max}
                step="1"
                value={params[name]}
                onChange={(event) => updateParam(name, event.target.value)}
                disabled={isRunning}
              />
            </label>
          ))}
          <label className="checkbox-setting">
            <span>{t.settings.ignoreHistory}</span>
            <input
              type="checkbox"
              checked={params.ignore_history}
              onChange={(event) => updateIgnoreHistory(event.target.checked)}
              disabled={isRunning}
            />
          </label>
          <label className="checkbox-setting">
            <span>{t.settings.allowRecentFallback}</span>
            <input
              type="checkbox"
              checked={params.allow_recent_fallback}
              onChange={(event) => updateAllowRecentFallback(event.target.checked)}
              disabled={isRunning}
            />
          </label>
          <label className="checkbox-setting">
            <span>{t.settings.preferGrowthProjects}</span>
            <input
              type="checkbox"
              checked={params.prefer_growth_projects}
              onChange={(event) => updatePreferGrowthProjects(event.target.checked)}
              disabled={isRunning}
            />
          </label>
          <p className="detail-note">{t.settings.preferNewProjects}</p>
        </form>
      </div>
    </section>
  );
}
