import { Link as LinkIcon } from "lucide-react";
import type { Language, Translation } from "../i18n";
import type { ReviewItem, ReviewSummary as ReviewSummaryData } from "../types";

type ReviewSummaryProps = {
  t: Translation;
  language: Language;
  summary?: ReviewSummaryData;
};

const scoreKeys: Array<keyof ReviewItem> = [
  "factual_score",
  "title_score",
  "structure_score",
  "readability_score",
  "completeness_score",
];

const maxScore = (key: keyof ReviewItem) => {
  if (key === "factual_score") return 30;
  if (key === "title_score" || key === "structure_score") return 20;
  return 15;
};

export function ReviewSummary({ t, language, summary }: ReviewSummaryProps) {
  const firstReview = summary?.reviews?.[0];
  const warnings = [
    ...(summary?.warnings || []),
    ...(firstReview?.issues || []),
    ...(firstReview?.revision_suggestions || []),
  ];
  const links = firstReview?.full_name ? [`https://github.com/${firstReview.full_name}`] : [];

  if (!summary || !summary.total_count) {
    return (
      <section className="panel review-panel">
        <div className="panel-header">
          <h2>{t.sections.reviewSummary}</h2>
        </div>
        <p className="empty-state">{t.empty.noReviewSummary}</p>
      </section>
    );
  }

  return (
    <section className="panel review-panel">
      <div className="panel-header">
        <h2>{t.sections.reviewSummary}</h2>
        <span className="soft-badge">{summary.pass_rate || "0%"}</span>
      </div>

      <div className="score-bars">
        {scoreKeys.map((key) => {
          const value = Number(firstReview?.[key] || 0);
          const max = maxScore(key);
          const width = `${Math.min(100, (value / max) * 100)}%`;
          return (
            <div className="score-bar-row" key={key}>
              <div className="score-bar-label">
                <span>{key}</span>
                <strong>{value}/{max}</strong>
              </div>
              <div className="score-bar-track">
                <span style={{ width }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="summary-block">
        <h3>{t.sections.factualWarnings}</h3>
        {warnings.length ? <ul>
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul> : <p className="empty-state">{language === "zh" ? "暂无事实风险提醒。" : "No factual warnings yet."}</p>}
      </div>

      <div className="summary-block">
        <h3>{t.sections.sourceLinks}</h3>
        <div className="source-links">
          {links.length ? links.map((link) => (
            <a href={link} target="_blank" rel="noreferrer" key={link}>
              <LinkIcon size={15} aria-hidden="true" />
              <span>{link}</span>
            </a>
          )) : <span className="empty-state">{language === "zh" ? "暂无来源链接。" : "No source links yet."}</span>}
        </div>
      </div>
    </section>
  );
}
