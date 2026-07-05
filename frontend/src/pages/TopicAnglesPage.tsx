import { ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchSnapshot } from "../api";
import type { Translation } from "../i18n";
import type { AnglesSnapshot, TopicAngle } from "../types";
import { asArray, projectName, projectUrl } from "./pageUtils";

type TopicAnglesPageProps = {
  t: Translation;
};

export function TopicAnglesPage({ t }: TopicAnglesPageProps) {
  const [snapshot, setSnapshot] = useState<AnglesSnapshot | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSnapshot<AnglesSnapshot>("angles")
      .then((payload) => {
        if (cancelled) return;
        setSnapshot(payload);
        setSelectedName(projectName(asArray(payload.angles)[0] || {}));
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load topic angles");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const angles = asArray(snapshot?.angles);
  const selected = useMemo(
    () => angles.find((angle) => projectName(angle) === selectedName) || angles[0],
    [angles, selectedName],
  );

  const renderList = (items: string[] | undefined) =>
    asArray(items).length ? <ul>{asArray(items).map((item) => <li key={item}>{item}</li>)}</ul> : <p className="empty-state">{t.empty.noData}</p>;

  return (
    <div className="split-page">
      <section className="panel list-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.pageTitles.topicAngles}</h2>
            <p>{t.pageSubtitles.topicAngles}</p>
          </div>
        </div>
        {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}
        {!loading && !error && angles.length === 0 ? <p className="empty-state">{t.empty.noTopicAngles}</p> : null}
        <div className="side-list">
          {angles.map((angle) => {
            const name = projectName(angle);
            return (
              <button className={`side-list-item ${name === projectName(selected || {}) ? "active" : ""}`} type="button" key={name} onClick={() => setSelectedName(name)}>
                <strong>{angle.project_name || name}</strong>
                <span>{angle.one_liner || angle.selected_angle || "-"}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="panel detail-panel">
        {selected ? (
          <>
            <div className="panel-header page-header">
              <div>
                <h2>{selected.project_name || projectName(selected)}</h2>
                <p>{selected.one_liner || t.empty.noData}</p>
              </div>
              <a className="icon-text-button" href={projectUrl(selected)} target="_blank" rel="noreferrer">
                <ExternalLink size={16} aria-hidden="true" />
                <span>{t.actions.openGithub}</span>
              </a>
            </div>

            <section className="detail-section">
              <h3>{t.labels.reasons}</h3>
              <p>{selected.selected_angle || t.empty.noData}</p>
            </section>

            <div className="detail-grid">
              <section className="detail-section">
                <h3>{t.labels.targetReaders}</h3>
                {renderList(selected.target_readers)}
              </section>
              <section className="detail-section">
                <h3>{t.labels.readerPainPoints}</h3>
                {renderList(selected.reader_pain_points)}
              </section>
              <section className="detail-section">
                <h3>{t.labels.sellingPoints}</h3>
                {renderList(selected.selling_points)}
              </section>
              <section className="detail-section">
                <h3>{t.labels.openingHook}</h3>
                <p>{selected.opening_hook || t.empty.noData}</p>
              </section>
            </div>

            <section className="detail-section">
              <h3>{t.labels.titleCandidates}</h3>
              <div className="item-stack">
                {asArray(selected.title_candidates).map((candidate) => (
                  <div className="detail-link-block static-block" key={candidate.title}>
                    <strong>{candidate.title || "-"}</strong>
                    <span>{candidate.style || "-"} · {candidate.reason || "-"}</span>
                    {candidate.risk ? <span>{candidate.risk}</span> : null}
                  </div>
                ))}
              </div>
            </section>

            <section className="detail-section">
              <h3>{t.labels.articleOutline}</h3>
              {renderList(selected.article_outline)}
            </section>

            <section className="detail-section">
              <h3>{t.labels.coverPrompt}</h3>
              <pre className="prompt-block">{selected.cover_prompt || t.empty.noData}</pre>
            </section>

            <section className="detail-section">
              <h3>{t.sections.factualWarnings}</h3>
              <div className="tag-list">
                {asArray(selected.factual_warnings).map((warning) => <span className="soft-badge failed" key={warning}>{warning}</span>)}
              </div>
              {!selected.factual_warnings?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>
          </>
        ) : (
          <p className="empty-state">{t.empty.noSelection}</p>
        )}
      </section>
    </div>
  );
}
