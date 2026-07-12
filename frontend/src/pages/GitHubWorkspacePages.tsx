import { ArrowRight, PackageCheck, Radar, Star, History } from "lucide-react";
import type { Language, Translation } from "../i18n";
import type { DashboardResponse, PageKey } from "../types";
import type { ContentVariant } from "../types";
import { ContentWorkspaceList } from "../components/ContentWorkspaceList";
import { CandidatesPage } from "./CandidatesPage";
import { ResearchNotesPage } from "./ResearchNotesPage";
import { RunsHistoryPage } from "./RunsHistoryPage";
import { ScoreRankingPage } from "./ScoreRankingPage";

export function GitHubWorkbenchPage({ t, dashboard, onNavigate }: { t: Translation; dashboard: DashboardResponse; onNavigate: (page: PageKey) => void }) {
  const actions: Array<{ page: PageKey; label: string }> = [
    { page: "github-discovery", label: t.nav.githubDiscovery },
    { page: "github-candidates", label: t.nav.githubCandidates },
    { page: "github-articles", label: t.nav.githubArticles },
  ];
  return <div className="page-stack workspace-page">
    <section className="workspace-metrics" aria-label={t.nav.githubWorkbench}>
      <div><Radar size={18} /><span>{t.nav.githubCandidates}</span><strong>{dashboard.stats?.today_candidates ?? 0}</strong></div>
      <div><Star size={18} /><span>{t.labels.qualityScore}</span><strong>{dashboard.stats?.average_quality_score ?? "-"}</strong></div>
      <div><PackageCheck size={18} /><span>{t.nav.githubArticles}</span><strong>{dashboard.stats?.final_articles ?? 0}</strong></div>
      <div><History size={18} /><span>{t.status.lastRun}</span><strong>{dashboard.run_info?.status || "-"}</strong></div>
    </section>
    <section className="panel page-panel workspace-actions"><div className="panel-header"><h2>{t.nav.githubGroup}</h2></div>
      <div>{actions.map((action) => <button className="workspace-link" type="button" key={action.page} onClick={() => onNavigate(action.page)}><span>{action.label}</span><ArrowRight size={16} /></button>)}</div>
    </section>
  </div>;
}

export function GitHubDiscoveryPage({ t }: { t: Translation }) { return <CandidatesPage t={t} />; }
export function GitHubCandidatesPage({ t }: { t: Translation }) { return <div className="page-stack"><CandidatesPage t={t} /><ScoreRankingPage t={t} /></div>; }
export function GitHubResearchPage({ t }: { t: Translation }) { return <ResearchNotesPage t={t} />; }
type ContentPageProps = { t: Translation; language: Language; onOpenLibrary: (contentId: string, variant: ContentVariant) => void };
export function GitHubArticlesPage({ t, language, onOpenLibrary }: ContentPageProps) {
  return <ContentWorkspaceList language={language} title={t.nav.githubArticles} types={["github_article", "github_custom_article"]} mode="github" onOpenLibrary={onOpenLibrary} />;
}
export function GitHubPackagesPage({ t, language, onOpenLibrary }: ContentPageProps) {
  return <ContentWorkspaceList language={language} title={t.nav.githubPackages} types={["github_article", "github_custom_article"]} mode="github" packageOnly onOpenLibrary={onOpenLibrary} />;
}
export function GitHubRunsPage({ t, onViewOutputs }: { t: Translation; onViewOutputs: (date: string) => void }) { return <RunsHistoryPage t={t} onViewOutputs={onViewOutputs} />; }
