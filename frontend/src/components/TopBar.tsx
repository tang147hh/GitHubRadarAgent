import { RefreshCw } from "lucide-react";
import type { Language, Translation } from "../i18n";
import { LanguageToggle } from "./LanguageToggle";

type TopBarProps = {
  t: Translation;
  language: Language;
  onLanguageChange: (language: Language) => void;
  title?: string;
  subtitle?: string;
  statuses: {
    github: string;
    llm: string;
    lastRun: string;
  };
  onRefresh: () => void;
  loading?: boolean;
};

export function TopBar({ t, language, onLanguageChange, title, subtitle, statuses, onRefresh, loading = false }: TopBarProps) {
  const badges = [
    { label: t.status.github, value: statuses.github },
    { label: t.status.llm, value: statuses.llm },
    { label: t.status.lastRun, value: statuses.lastRun },
  ];

  return (
    <header className="topbar">
      <div className="topbar-title">
        <h1>{title || t.dashboard}</h1>
        <p>{subtitle || t.subtitle}</p>
      </div>

      <div className="topbar-actions">
        <div className="status-badges">
          {badges.map((badge) => (
            <span className="status-badge" key={badge.label}>
              <span>{badge.label}</span>
              <strong>{badge.value}</strong>
            </span>
          ))}
        </div>
        <LanguageToggle language={language} onChange={onLanguageChange} />
        <button className="secondary-button" type="button" onClick={onRefresh} disabled={loading}>
          <RefreshCw className={loading ? "spin-icon" : ""} size={17} aria-hidden="true" />
          <span>{loading ? t.actions.refreshing : t.actions.refresh}</span>
        </button>
      </div>
    </header>
  );
}
