import { useEffect, useMemo, useState } from "react";
import { fetchSnapshot } from "../api";
import type { Translation } from "../i18n";
import type { ScoreRankingItem, ScoreSnapshot } from "../types";
import { asArray, formatDate, projectName, projectUrl } from "./pageUtils";

type ScoreRankingPageProps = {
  t: Translation;
};

const numericScore = (item: ScoreRankingItem, key: keyof ScoreRankingItem) => {
  const value = item[key];
  return typeof value === "number" ? value : 0;
};

export function ScoreRankingPage({ t }: ScoreRankingPageProps) {
  const [snapshot, setSnapshot] = useState<ScoreSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSnapshot<ScoreSnapshot>("score")
      .then((payload) => {
        if (!cancelled) {
          setSnapshot(payload);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load score ranking");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const scores = useMemo(
    () => [...asArray(snapshot?.scores)].sort((a, b) => (b.total_score ?? b.score ?? 0) - (a.total_score ?? a.score ?? 0)),
    [snapshot],
  );

  return (
    <section className="panel page-panel">
      <div className="panel-header page-header">
        <div>
          <h2>{t.pageTitles.scoreRanking}</h2>
          <p>{t.pageSubtitles.scoreRanking}</p>
        </div>
        {snapshot?.generated_at ? <span className="soft-badge unknown">{t.labels.generatedAt}: {formatDate(snapshot.generated_at)}</span> : null}
      </div>

      {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
      {error ? <div className="banner error">{error}</div> : null}

      {!loading && !error ? (
        <div className="table-wrap">
          <table className="ranking-table data-table wide-table">
            <thead>
              <tr>
                <th>{t.labels.rank}</th>
                <th>{t.labels.project}</th>
                <th>{t.labels.totalScore}</th>
                <th>{t.labels.growth}</th>
                <th>{t.labels.velocity}</th>
                <th>{t.labels.freshness}</th>
                <th>{t.labels.relevance}</th>
                <th>{t.labels.quality}</th>
                <th>{t.labels.activity}</th>
                <th>{t.labels.communication}</th>
                <th>{t.labels.discoveryReason}</th>
                <th>{t.labels.reasons}</th>
                <th>{t.labels.warnings}</th>
              </tr>
            </thead>
            <tbody>
              {scores.length ? scores.map((item, index) => (
                <tr key={projectName(item)}>
                  <td>#{index + 1}</td>
                  <td>
                    <a href={projectUrl(item)} target="_blank" rel="noreferrer">
                      {projectName(item)}
                    </a>
                  </td>
                  <td><strong>{(item.total_score ?? item.score ?? 0).toFixed(1)}</strong></td>
                  <td>{numericScore(item, "growth_score").toFixed(1)}</td>
                  <td>{numericScore(item, "velocity_score").toFixed(1)}</td>
                  <td>{numericScore(item, "freshness_score").toFixed(1)}</td>
                  <td>{numericScore(item, "relevance_score").toFixed(1)}</td>
                  <td>{numericScore(item, "quality_score").toFixed(1)}</td>
                  <td>{numericScore(item, "activity_score").toFixed(1)}</td>
                  <td>{numericScore(item, "communication_score").toFixed(1)}</td>
                  <td><span className="soft-badge unknown">{item.discovery_reason || "-"}</span></td>
                  <td>
                    <div className="tag-list">
                      {asArray(item.reasons).slice(0, 4).map((reason) => <span className="soft-badge unknown" key={reason}>{reason}</span>)}
                    </div>
                  </td>
                  <td>
                    <div className="tag-list">
                      {asArray(item.warnings).map((warning) => <span className="soft-badge failed" key={warning}>{warning}</span>)}
                    </div>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={13} className="empty-table-cell">{t.empty.noScoreRanking}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
