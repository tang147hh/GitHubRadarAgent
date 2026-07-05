import { useEffect, useMemo, useState } from "react";
import { fetchLatestRun, fetchRuns } from "../api";
import type { Translation } from "../i18n";
import type { LatestRunResponse, RunHistoryItem } from "../types";
import { asArray, formatDate } from "./pageUtils";

type RunsHistoryPageProps = {
  t: Translation;
  onViewOutputs: (date: string) => void;
};

function outputDateForRun(run?: Pick<RunHistoryItem, "date" | "output_dir"> | null) {
  if (run?.date) return run.date;
  const match = run?.output_dir?.match(/\d{4}-\d{2}-\d{2}/);
  return match?.[0] || "";
}

function bucketCount(run: RunHistoryItem | null | undefined, bucket: string) {
  const values = run?.selection_summary?.selection_buckets?.[bucket];
  return Array.isArray(values) ? values.length : 0;
}

export function RunsHistoryPage({ t, onViewOutputs }: RunsHistoryPageProps) {
  const [runs, setRuns] = useState<RunHistoryItem[]>([]);
  const [latest, setLatest] = useState<LatestRunResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchRuns(), fetchLatestRun()])
      .then(([runsPayload, latestPayload]) => {
        if (cancelled) return;
        setRuns(runsPayload.runs || []);
        setLatest(latestPayload);
        setSelectedRunId(latestPayload.run_id || runsPayload.runs?.[0]?.run_id || "");
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load runs");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedRun = useMemo(() => {
    if (latest?.run_id === selectedRunId) return latest;
    return runs.find((run) => run.run_id === selectedRunId) || latest || runs[0];
  }, [latest, runs, selectedRunId]);

  return (
    <div className="page-stack">
      <section className="panel page-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.pageTitles.runsHistory}</h2>
            <p>{t.pageSubtitles.runsHistory}</p>
          </div>
        </div>
        {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}
        {latest?.exists === false ? <p className="empty-state">{latest.message || t.empty.noRuns}</p> : null}

        {latest?.exists !== false && latest ? (
          <>
            <div className="info-grid">
              <div><span>{t.labels.runId}</span><strong>{latest.run_id || "-"}</strong></div>
              <div><span>{t.labels.date}</span><strong>{latest.date || "-"}</strong></div>
              <div><span>{t.labels.status}</span><strong>{latest.status || "-"}</strong></div>
              <div><span>{t.labels.output}</span><strong>{latest.output_dir || "-"}</strong></div>
              <div><span>{t.labels.highScoreProjects}</span><strong>{bucketCount(latest, "top_score")}</strong></div>
              <div><span>{t.labels.freshCandidates}</span><strong>{latest.selection_summary?.fresh_candidate_count ?? 0}</strong></div>
              <div><span>{t.labels.skippedRecent}</span><strong>{latest.selection_summary?.skipped_recent_count ?? 0}</strong></div>
              <div><span>{t.labels.recentGrowth}</span><strong>{latest.selection_summary?.growth_selected_count ?? 0}</strong></div>
              <div><span>{t.labels.practicalTool}</span><strong>{bucketCount(latest, "practical_tool") || latest.selection_summary?.tool_selected_count || 0}</strong></div>
            </div>
            {outputDateForRun(latest) ? (
              <button className="secondary-button" type="button" onClick={() => onViewOutputs(outputDateForRun(latest))}>
                {t.actions.viewOutputs}
              </button>
            ) : null}
          </>
        ) : null}
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.sections.runStages}</h2>
          {selectedRun?.run_id ? <span className="soft-badge unknown">{selectedRun.run_id}</span> : null}
        </div>
        <div className="stage-list">
          {asArray(selectedRun?.stages).map((stage) => (
            <div className="stage-row" key={stage.name}>
              <span className={`soft-badge ${stage.status || "unknown"}`}>{stage.name}</span>
              <strong>{stage.status || "-"}</strong>
              <p>{stage.message || stage.error || "-"}</p>
              <small>{formatDate(stage.started_at)} → {formatDate(stage.finished_at)}</small>
            </div>
          ))}
          {!selectedRun?.stages?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
        </div>
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.sections.latestRun}</h2>
        </div>
        <div className="table-wrap">
          <table className="ranking-table data-table">
            <thead>
              <tr>
                <th>{t.labels.runId}</th>
                <th>{t.labels.date}</th>
                <th>{t.labels.status}</th>
                <th>{t.labels.started}</th>
                <th>{t.labels.finished}</th>
                <th>{t.labels.error}</th>
                <th>{t.actions.view}</th>
              </tr>
            </thead>
            <tbody>
              {runs.length ? runs.map((run) => (
                <tr className={run.run_id === selectedRunId ? "selected-row" : ""} key={run.run_id || run.file}>
                  <td>
                    <button className="link-button" type="button" onClick={() => setSelectedRunId(run.run_id || "")}>
                      {run.run_id || "-"}
                    </button>
                  </td>
                  <td>{run.date || "-"}</td>
                  <td><span className={`soft-badge ${run.status || "unknown"}`}>{run.status || "-"}</span></td>
                  <td>{formatDate(run.started_at)}</td>
                  <td>{formatDate(run.finished_at)}</td>
                  <td>{run.error || "-"}</td>
                  <td>
                    {outputDateForRun(run) ? (
                      <button className="link-button" type="button" onClick={() => onViewOutputs(outputDateForRun(run))}>
                        {t.actions.viewOutputs}
                      </button>
                    ) : "-"}
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={7} className="empty-table-cell">{t.empty.noRuns}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
