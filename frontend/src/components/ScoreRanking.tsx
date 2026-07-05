import type { Translation } from "../i18n";
import type { ScoreRankingItem } from "../types";

type ScoreRankingProps = {
  t: Translation;
  items: ScoreRankingItem[];
};

const formatStars = (item: ScoreRankingItem) => {
  const raw = item.stars ?? item.stargazers_count;
  if (typeof raw === "number") {
    return raw >= 1000 ? `${(raw / 1000).toFixed(raw >= 10000 ? 0 : 1)}k` : String(raw);
  }
  return raw || "-";
};

const projectName = (item: ScoreRankingItem) => item.full_name || item.project || "-";
const projectScore = (item: ScoreRankingItem) => item.total_score ?? item.score ?? 0;

export function ScoreRanking({ t, items }: ScoreRankingProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{t.sections.scoreRanking}</h2>
      </div>

      <div className="table-wrap">
        <table className="ranking-table">
          <thead>
            <tr>
              <th>{t.labels.rank}</th>
              <th>{t.labels.project}</th>
              <th>{t.labels.stars}</th>
              <th>{t.labels.score}</th>
              <th>{t.labels.velocity}</th>
              <th>{t.labels.discoveryReason}</th>
              <th>{t.labels.language}</th>
              <th>{t.labels.status}</th>
            </tr>
          </thead>
          <tbody>
            {items.length ? items.map((project, index) => (
              <tr key={projectName(project)}>
                <td>#{project.rank ?? index + 1}</td>
                <td>
                  <a href={project.html_url || `https://github.com/${projectName(project)}`} target="_blank" rel="noreferrer">
                    {projectName(project)}
                  </a>
                </td>
                <td>{formatStars(project)}</td>
                <td>
                  <strong>{projectScore(project).toFixed(1)}</strong>
                </td>
                <td>{(project.velocity_score ?? 0).toFixed(1)}</td>
                <td><span className="soft-badge unknown">{project.discovery_reason || "-"}</span></td>
                <td>{project.language || "-"}</td>
                <td>
                  <span className="soft-badge">{project.status || t.status.selected}</span>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={8} className="empty-table-cell">{t.empty.noScoreRanking}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
