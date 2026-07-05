import { ExternalLink, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchSnapshot } from "../api";
import type { Translation } from "../i18n";
import type { CandidateItem, DiscoverySnapshot } from "../types";
import { asArray, formatDate, formatNumber, projectName, projectUrl } from "./pageUtils";

type CandidatesPageProps = {
  t: Translation;
};

export function CandidatesPage({ t }: CandidatesPageProps) {
  const [snapshot, setSnapshot] = useState<DiscoverySnapshot | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSnapshot<DiscoverySnapshot>("discovery")
      .then((payload) => {
        if (!cancelled) {
          setSnapshot(payload);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load candidates");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const candidates = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return asArray<CandidateItem>(snapshot?.candidates).filter((candidate) => {
      if (!normalizedQuery) return true;
      return `${projectName(candidate)} ${candidate.description || ""}`.toLowerCase().includes(normalizedQuery);
    });
  }, [query, snapshot]);

  return (
    <section className="panel page-panel">
      <div className="panel-header page-header">
        <div>
          <h2>{t.pageTitles.candidates}</h2>
          <p>{t.pageSubtitles.candidates}</p>
        </div>
        {snapshot?.generated_at ? <span className="soft-badge unknown">{t.labels.generatedAt}: {formatDate(snapshot.generated_at)}</span> : null}
      </div>

      <label className="search-box">
        <Search size={16} aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`${t.labels.search}: ${t.labels.project} / ${t.labels.description}`}
        />
      </label>

      {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
      {error ? <div className="banner error">{error}</div> : null}

      {!loading && !error ? (
        <div className="table-wrap">
          <table className="ranking-table data-table">
            <thead>
              <tr>
                <th>{t.labels.project}</th>
                <th>{t.labels.stars}</th>
                <th>{t.labels.forks}</th>
                <th>{t.labels.language}</th>
                <th>{t.labels.topics}</th>
                <th>{t.labels.updated} / {t.labels.pushed}</th>
                <th>{t.labels.url}</th>
              </tr>
            </thead>
            <tbody>
              {candidates.length ? candidates.map((candidate) => {
                const url = projectUrl(candidate);
                return (
                  <tr key={projectName(candidate)}>
                    <td>
                      <strong>{projectName(candidate)}</strong>
                      <span className="muted-line">{candidate.description || "-"}</span>
                    </td>
                    <td>{formatNumber(candidate.stars ?? candidate.stargazers_count)}</td>
                    <td>{formatNumber(candidate.forks ?? candidate.forks_count)}</td>
                    <td>{candidate.language || "-"}</td>
                    <td>
                      <div className="tag-list compact">
                        {asArray(candidate.topics).slice(0, 5).map((topic) => <span className="soft-badge unknown" key={topic}>{topic}</span>)}
                      </div>
                    </td>
                    <td>
                      <span className="muted-line">{t.labels.updated}: {formatDate(candidate.updated_at)}</span>
                      <span className="muted-line">{t.labels.pushed}: {formatDate(candidate.pushed_at)}</span>
                    </td>
                    <td>
                      {url ? (
                        <a className="project-link" href={url} target="_blank" rel="noreferrer">
                          <ExternalLink size={15} aria-hidden="true" />
                          <span>{url}</span>
                        </a>
                      ) : "-"}
                    </td>
                  </tr>
                );
              }) : (
                <tr>
                  <td colSpan={7} className="empty-table-cell">{t.empty.noCandidates}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
