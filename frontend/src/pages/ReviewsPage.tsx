import { useEffect, useMemo, useState } from "react";
import { fetchReport, fetchSnapshot } from "../api";
import type { Translation } from "../i18n";
import type { ArticleQualityReport, ArticleQualitySnapshot, HumanizationReportItem, ReviewItem, ReviewsSnapshot } from "../types";
import { asArray, reviewMaxScore, scorePercent } from "./pageUtils";

type ReviewsPageProps = {
  t: Translation;
};

const scoreKeys: Array<keyof ReviewItem> = [
  "factual_score",
  "title_score",
  "structure_score",
  "readability_score",
  "completeness_score",
];

const qualityScoreKeys: Array<keyof ArticleQualityReport> = [
  "title_score",
  "opening_score",
  "project_value_score",
  "concrete_example_score",
  "effect_depth_score",
  "readability_score",
  "human_tone_score",
  "anti_readme_score",
  "wechat_style_score",
];

export function ReviewsPage({ t }: ReviewsPageProps) {
  const [snapshot, setSnapshot] = useState<ReviewsSnapshot | null>(null);
  const [humanizationReports, setHumanizationReports] = useState<HumanizationReportItem[]>([]);
  const [qualitySnapshot, setQualitySnapshot] = useState<ArticleQualitySnapshot | null>(null);
  const [reportPath, setReportPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([
      fetchSnapshot<ReviewsSnapshot>("reviews"),
      fetchSnapshot<{ reports?: HumanizationReportItem[] }>("humanization"),
      fetchSnapshot<ArticleQualitySnapshot>("article_quality"),
      fetchReport("review_report"),
    ])
      .then(([snapshotResult, humanizationResult, qualityResult, reportResult]) => {
        if (cancelled) return;
        if (snapshotResult.status === "fulfilled") {
          setSnapshot(snapshotResult.value);
          setError("");
        } else {
          setError(snapshotResult.reason instanceof Error ? snapshotResult.reason.message : "Failed to load reviews");
        }
        if (humanizationResult.status === "fulfilled") {
          setHumanizationReports(asArray(humanizationResult.value.reports));
        }
        if (qualityResult.status === "fulfilled") {
          setQualitySnapshot(qualityResult.value);
        }
        if (reportResult.status === "fulfilled") setReportPath(reportResult.value.path || "");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const reviews = asArray(snapshot?.reviews);
  const humanizationByName = useMemo(() => {
    const entries = humanizationReports
      .filter((report) => report.full_name)
      .map((report) => [report.full_name || "", report] as const);
    return new Map(entries);
  }, [humanizationReports]);
  const qualityByName = useMemo(() => {
    const entries = asArray(qualitySnapshot?.reports)
      .filter((report) => report.full_name)
      .map((report) => [report.full_name || "", report] as const);
    return new Map(entries);
  }, [qualitySnapshot]);
  const summary = useMemo(() => {
    const total = reviews.length;
    const pass = reviews.filter((review) => review.pass_review).length;
    return {
      total,
      pass,
      passRate: total ? `${Math.round((pass / total) * 100)}%` : "0%",
      average: total ? (reviews.reduce((sum, review) => sum + (review.total_score || 0), 0) / total).toFixed(1) : "0.0",
      qualityAverage: qualitySnapshot?.average_score != null ? Number(qualitySnapshot.average_score).toFixed(1) : "0.0",
      qualityLow: qualitySnapshot?.low_quality_count ?? 0,
    };
  }, [reviews, qualitySnapshot]);

  return (
    <div className="page-stack">
      <section className="panel page-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.pageTitles.reviews}</h2>
            <p>{t.pageSubtitles.reviews}</p>
          </div>
          {reportPath ? <span className="soft-badge unknown">{reportPath}</span> : null}
        </div>

        {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}

        <div className="stats-grid compact-stats">
          <div className="mini-stat"><span>{t.labels.totalReviews}</span><strong>{summary.total}</strong></div>
          <div className="mini-stat"><span>{t.labels.passReview}</span><strong>{summary.pass}</strong></div>
          <div className="mini-stat"><span>{t.stats.reviewPassRate}</span><strong>{summary.passRate}</strong></div>
          <div className="mini-stat"><span>{t.labels.totalScore}</span><strong>{summary.average}</strong></div>
          <div className="mini-stat"><span>{t.stats.averageQualityScore}</span><strong>{summary.qualityAverage}</strong></div>
          <div className="mini-stat"><span>{t.labels.needsRevision}</span><strong>{summary.qualityLow}</strong></div>
        </div>
      </section>

      <section className="review-card-list">
        {!loading && !error && reviews.length === 0 ? <p className="empty-state">{t.empty.noReviews}</p> : null}
        {reviews.map((review) => {
          const humanization = humanizationByName.get(review.full_name || "");
          const quality = qualityByName.get(review.full_name || "");
          return (
          <article className="panel review-card" key={`${review.full_name}-${review.title}`}>
            <div className="panel-header page-header">
              <div>
                <h2>{review.title || review.full_name || "-"}</h2>
                <p>{review.full_name || "-"}</p>
              </div>
              <span className={`soft-badge ${review.pass_review ? "" : "failed"}`}>
                {review.pass_review ? t.status.success : t.status.failed} · {review.total_score ?? 0}
              </span>
              {quality ? (
                <span className={`soft-badge ${quality.publish_ready ? "" : "failed"}`}>
                  {t.labels.qualityScore}: {quality.total_score ?? 0} ·{" "}
                  {quality.publish_ready ? t.labels.publishable : t.labels.needsRevision}
                </span>
              ) : null}
            </div>

            <div className="score-bars">
              {scoreKeys.map((key) => {
                const value = Number(review[key] || 0);
                const max = reviewMaxScore(key);
                return (
                  <div className="score-bar-row" key={key}>
                    <div className="score-bar-label">
                      <span>{key}</span>
                      <strong>{value}/{max}</strong>
                    </div>
                    <div className="score-bar-track">
                      <span style={{ width: scorePercent(value, max) }} />
                    </div>
                  </div>
                );
              })}
            </div>

            {quality ? (
              <div className="score-bars">
                {qualityScoreKeys.map((key) => {
                  const value = Number(quality[key] || 0);
                  return (
                    <div className="score-bar-row" key={key}>
                      <div className="score-bar-label">
                        <span>{key}</span>
                        <strong>{value}/100</strong>
                      </div>
                      <div className="score-bar-track">
                        <span style={{ width: scorePercent(value, 100) }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div className="detail-grid">
              <section className="detail-section">
                <h3>{t.sections.strengths}</h3>
                <ul>{asArray(review.strengths).map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
              <section className="detail-section">
                <h3>{t.sections.issues}</h3>
                <ul>{asArray(review.issues).map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
              <section className="detail-section">
                <h3>{t.sections.revisionSuggestions}</h3>
                <ul>{asArray(review.revision_suggestions).map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
              <section className="detail-section">
                <h3>{t.labels.reviewMode}</h3>
                <p>{review.review_mode || "-"}</p>
              </section>
              <section className="detail-section">
                <h3>{t.sections.humanization}</h3>
                <p>
                  {t.labels.naturalness}: {humanization?.ai_smell_score ?? "-"} ·{" "}
                  {t.labels.templateRisk}: {humanization?.template_risk ?? "-"} ·{" "}
                  {t.labels.localizationScore}: {humanization?.localization_score ?? "-"}
                </p>
              </section>
              <section className="detail-section">
                <h3>{t.labels.articleQuality}</h3>
                <p>{quality?.summary || "-"}</p>
                <ul>{asArray(quality?.issues).slice(0, 5).map((item) => (
                  <li key={`${item.issue_type}-${item.description}`}>
                    {item.issue_type}: {item.description}
                    {item.evidence ? ` (${item.evidence})` : ""}
                  </li>
                ))}</ul>
              </section>
              <section className="detail-section">
                <h3>{t.sections.revisionSuggestions}</h3>
                <ul>{asArray(quality?.rewrite_recommendations).map((item) => <li key={item}>{item}</li>)}</ul>
              </section>
            </div>
          </article>
          );
        })}
      </section>
    </div>
  );
}
