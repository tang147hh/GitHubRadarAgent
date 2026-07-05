import { ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchSnapshot } from "../api";
import type { Translation } from "../i18n";
import type { ResearchNote, ResearchSnapshot } from "../types";
import { asArray, formatDate, formatNumber, projectName, projectUrl } from "./pageUtils";

type ResearchNotesPageProps = {
  t: Translation;
};

function LinkList({ links }: { links: string[] }) {
  if (!links.length) return null;
  return (
    <div className="source-links">
      {links.map((link) => (
        <a href={link} target="_blank" rel="noreferrer" key={link}>
          <ExternalLink size={15} aria-hidden="true" />
          <span>{link}</span>
        </a>
      ))}
    </div>
  );
}

export function ResearchNotesPage({ t }: ResearchNotesPageProps) {
  const [snapshot, setSnapshot] = useState<ResearchSnapshot | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSnapshot<ResearchSnapshot>("research")
      .then((payload) => {
        if (cancelled) return;
        setSnapshot(payload);
        setSelectedName(projectName(asArray(payload.notes)[0] || {}));
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load research notes");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const notes = asArray(snapshot?.notes);
  const selected = useMemo(
    () => notes.find((note) => projectName(note) === selectedName) || notes[0],
    [notes, selectedName],
  );

  return (
    <div className="split-page">
      <section className="panel list-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.pageTitles.researchNotes}</h2>
            <p>{t.pageSubtitles.researchNotes}</p>
          </div>
        </div>
        {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}
        {!loading && !error && notes.length === 0 ? <p className="empty-state">{t.empty.noResearchNotes}</p> : null}
        <div className="side-list">
          {notes.map((note) => {
            const name = projectName(note);
            return (
              <button className={`side-list-item ${name === projectName(selected || {}) ? "active" : ""}`} type="button" key={name} onClick={() => setSelectedName(name)}>
                <strong>{name}</strong>
                <span>{note.description || note.language || "-"}</span>
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
                <h2>{projectName(selected)}</h2>
                <p>{selected.description || t.empty.noData}</p>
              </div>
              <a className="icon-text-button" href={projectUrl(selected)} target="_blank" rel="noreferrer">
                <ExternalLink size={16} aria-hidden="true" />
                <span>{t.actions.openGithub}</span>
              </a>
            </div>

            <div className="info-grid">
              <div><span>{t.labels.stars}</span><strong>{formatNumber(selected.stars)}</strong></div>
              <div><span>{t.labels.forks}</span><strong>{formatNumber(selected.forks)}</strong></div>
              <div><span>{t.labels.language}</span><strong>{selected.language || "-"}</strong></div>
              <div><span>{t.labels.pushed}</span><strong>{formatDate(selected.pushed_at)}</strong></div>
              <div><span>{t.labels.projectKind}</span><strong>{selected.project_kind || "-"}</strong></div>
            </div>

            <section className="detail-section">
              <h3>{t.sections.authorProfile}</h3>
              {selected.author_profile ? (
                <div className="item-stack">
                  <a className="detail-link-block" href={selected.author_profile.html_url || "#"} target="_blank" rel="noreferrer">
                    <strong>{selected.author_profile.name || selected.author_profile.login || "-"}</strong>
                    <span>{[selected.author_profile.type, selected.author_profile.company, selected.author_profile.location].filter(Boolean).join(" · ") || "-"}</span>
                  </a>
                  {selected.author_profile.bio ? <p>{selected.author_profile.bio}</p> : null}
                  <div className="tag-list">
                    {selected.author_profile.followers !== undefined && selected.author_profile.followers !== null ? <span className="soft-badge">{t.labels.followers}: {formatNumber(selected.author_profile.followers)}</span> : null}
                    {selected.author_profile.public_repos !== undefined && selected.author_profile.public_repos !== null ? <span className="soft-badge">{t.labels.publicRepos}: {formatNumber(selected.author_profile.public_repos)}</span> : null}
                  </div>
                </div>
              ) : <p className="empty-state">{t.empty.noData}</p>}
            </section>

            <section className="detail-section">
              <h3>{t.sections.projectLinks}</h3>
              <div className="item-stack">
                {selected.project_links?.homepage ? (
                  <a className="detail-link-block" href={selected.project_links.homepage} target="_blank" rel="noreferrer">
                    <strong>{t.labels.homepage}</strong>
                    <span>{selected.project_links.homepage}</span>
                  </a>
                ) : null}
                {asArray(selected.project_links?.documentation).length ? (
                  <div>
                    <strong>{t.labels.documentation}</strong>
                    <LinkList links={asArray(selected.project_links?.documentation).slice(0, 5)} />
                  </div>
                ) : null}
                {asArray(selected.project_links?.demo).length ? (
                  <div>
                    <strong>{t.labels.demo}</strong>
                    <LinkList links={asArray(selected.project_links?.demo).slice(0, 5)} />
                  </div>
                ) : null}
                {asArray(selected.project_links?.examples).length ? (
                  <div>
                    <strong>{t.labels.examples}</strong>
                    <LinkList links={asArray(selected.project_links?.examples).slice(0, 5)} />
                  </div>
                ) : null}
              </div>
              {!selected.project_links?.homepage && !asArray(selected.project_links?.documentation).length && !asArray(selected.project_links?.demo).length && !asArray(selected.project_links?.examples).length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>

            <section className="detail-section">
              <h3>{t.sections.toolUseCases}</h3>
              <ul>{asArray(selected.tool_use_cases).map((item) => <li key={item}>{item}</li>)}</ul>
              {!selected.tool_use_cases?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>

            <section className="detail-section">
              <h3>{t.sections.readmeSummary}</h3>
              <p>{selected.readme_summary || t.empty.noData}</p>
            </section>

            <section className="detail-section">
              <h3>{t.sections.readmeKeyPoints}</h3>
              <ul>{asArray(selected.readme_key_points).map((point) => <li key={point}>{point}</li>)}</ul>
              {!selected.readme_key_points?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>

            <section className="detail-section">
              <h3>{t.sections.readmeMedia}</h3>
              <LinkList links={asArray(selected.readme_images).slice(0, 10)} />
              {!selected.readme_images?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>

            <section className="detail-section">
              <h3>{t.sections.releases}</h3>
              <div className="item-stack">
                {asArray(selected.releases).map((release) => (
                  <a className="detail-link-block" href={release.html_url} target="_blank" rel="noreferrer" key={release.html_url || release.tag_name}>
                    <strong>{release.name || release.tag_name || "-"}</strong>
                    <span>{formatDate(release.published_at)}</span>
                  </a>
                ))}
              </div>
              {!selected.releases?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>

            <section className="detail-section">
              <h3>{t.sections.openIssues}</h3>
              <div className="item-stack">
                {asArray(selected.open_issues).map((issue) => (
                  <a className="detail-link-block" href={issue.html_url} target="_blank" rel="noreferrer" key={issue.html_url || issue.title}>
                    <strong>{issue.title || "-"}</strong>
                    <span>{formatDate(issue.created_at)} · {issue.comments ?? 0} comments</span>
                  </a>
                ))}
              </div>
              {!selected.open_issues?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>

            <section className="detail-section">
              <h3>{t.sections.sourceLinks}</h3>
              <LinkList links={asArray(selected.source_links)} />
            </section>

            <section className="detail-section">
              <h3>{t.sections.risks}</h3>
              <div className="tag-list">{asArray(selected.risks).map((risk) => <span className="soft-badge failed" key={risk}>{risk}</span>)}</div>
              {!selected.risks?.length ? <p className="empty-state">{t.empty.noData}</p> : null}
            </section>
          </>
        ) : (
          <p className="empty-state">{t.empty.noSelection}</p>
        )}
      </section>
    </div>
  );
}
