import {
  Archive,
  BarChart3,
  ChevronLeft,
  CircleDot,
  ClipboardCheck,
  Compass,
  FileArchive,
  FileText,
  Files,
  Goal,
  History,
  LayoutDashboard,
  ListChecks,
  NotebookText,
  Newspaper,
  PackageCheck,
  PanelTop,
  RefreshCcw,
  Radar,
  Send,
  Search,
  SquareTerminal,
  Settings,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { Translation } from "../i18n";
import type { PageKey } from "../types";

type SidebarProps = {
  t: Translation;
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
};

export function Sidebar({ t, activePage, onNavigate }: SidebarProps) {
  const navGroups = [
    { label: t.nav.overviewGroup, items: [
      { key: "dashboard", label: t.nav.dashboard, icon: LayoutDashboard },
      { key: "content-library", label: t.nav.contentLibrary, icon: Archive },
      { key: "publishing-desk", label: t.nav.publishingDesk, icon: Send },
    ] },
    { label: t.nav.githubGroup, items: [
      { key: "github-workbench", label: t.nav.githubWorkbench, icon: PanelTop },
      { key: "github-discovery", label: t.nav.githubDiscovery, icon: Compass },
      { key: "github-candidates", label: t.nav.githubCandidates, icon: ListChecks },
      { key: "github-research", label: t.nav.githubResearch, icon: NotebookText },
      { key: "github-articles", label: t.nav.githubArticles, icon: FileText },
      { key: "github-packages", label: t.nav.githubPackages, icon: PackageCheck },
      { key: "github-runs", label: t.nav.githubRuns, icon: History },
    ] },
    { label: t.nav.aiNewsGroup, items: [
      { key: "ai-news-workbench", label: t.nav.aiNewsWorkbench, icon: Newspaper },
      { key: "ai-news-collect", label: t.nav.aiNewsCollect, icon: RefreshCcw },
      { key: "ai-news-list", label: t.nav.aiNewsList, icon: Files },
      { key: "ai-news-detail", label: t.nav.aiNewsDetail, icon: Search },
      { key: "ai-news-selection", label: t.nav.aiNewsSelection, icon: CircleDot },
      { key: "ai-news-plan", label: t.nav.aiNewsPlan, icon: ClipboardCheck },
      { key: "ai-news-articles", label: t.nav.aiNewsArticles, icon: FileText },
      { key: "ai-news-digest", label: t.nav.aiNewsDigest, icon: Sparkles },
      { key: "ai-news-reports", label: t.nav.aiNewsReports, icon: FileArchive },
    ] },
    { label: t.nav.agentGroup, items: [
      { key: "agent-workbench", label: t.nav.agentWorkbench, icon: SquareTerminal },
      { key: "agent-goal", label: t.nav.agentGoal, icon: Goal },
      { key: "agent-plan", label: t.nav.agentPlan, icon: ListChecks },
      { key: "agent-tools", label: t.nav.agentTools, icon: Wrench },
      { key: "agent-reflections", label: t.nav.agentReflections, icon: RefreshCcw },
      { key: "agent-approvals", label: t.nav.agentApprovals, icon: ClipboardCheck },
      { key: "agent-artifacts", label: t.nav.agentArtifacts, icon: Archive },
      { key: "agent-runs", label: t.nav.agentRuns, icon: History },
    ] },
    { label: t.nav.systemGroup, items: [
      { key: "reports", label: t.nav.reports, icon: Files },
      { key: "settings", label: t.nav.settings, icon: Settings },
    ] },
  ];

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <Radar size={22} aria-hidden="true" />
        </div>
        <span>{t.appName}</span>
      </div>

      <nav className="sidebar-nav" aria-label="Main navigation">
        {navGroups.map((group) => (
          <section className="nav-group" key={group.label}>
            <h2>{group.label}</h2>
            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = item.key === activePage;
              return (
                <button
                  className={`nav-item ${isActive ? "active" : ""}`}
                  type="button"
                  key={item.key}
                  onClick={() => onNavigate(item.key as PageKey)}
                  aria-current={isActive ? "page" : undefined}
                >
                  <Icon size={17} aria-hidden="true" />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </section>
        ))}
      </nav>

      <button className="collapse-button" type="button">
        <ChevronLeft size={18} aria-hidden="true" />
        <span>{t.nav.collapse}</span>
      </button>

      <div className="sidebar-footer">
        <BarChart3 size={16} aria-hidden="true" />
        <span>Daily Radar v0.1</span>
      </div>
    </aside>
  );
}
