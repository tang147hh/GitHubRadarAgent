import {
  BarChart3,
  BookOpenCheck,
  ChevronLeft,
  FileText,
  Files,
  History,
  LayoutDashboard,
  ListChecks,
  NotebookText,
  Newspaper,
  PenLine,
  PencilLine,
  Radar,
  Rocket,
  Settings,
  Trophy,
} from "lucide-react";
import type { Translation } from "../i18n";
import type { PageKey } from "../types";

type SidebarProps = {
  t: Translation;
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
};

export function Sidebar({ t, activePage, onNavigate }: SidebarProps) {
  const navItems = [
    { key: "dashboard", label: t.nav.dashboard, icon: LayoutDashboard },
    { key: "dashboard", label: t.nav.runDaily, icon: Rocket },
    { key: "customArticle", label: t.nav.customArticle, icon: PencilLine },
    { key: "candidates", label: t.nav.candidates, icon: ListChecks },
    { key: "scoreRanking", label: t.nav.scoreRanking, icon: Trophy },
    { key: "researchNotes", label: t.nav.researchNotes, icon: NotebookText },
    { key: "topicAngles", label: t.nav.topicAngles, icon: PenLine },
    { key: "articles", label: t.nav.articles, icon: FileText },
    { key: "aiNews", label: t.nav.aiNews, icon: Newspaper },
    { key: "reports", label: t.nav.reports, icon: Files },
    { key: "reviews", label: t.nav.reviews, icon: BookOpenCheck },
    { key: "runsHistory", label: t.nav.runsHistory, icon: History },
    { key: "settings", label: t.nav.settings, icon: Settings },
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
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.key === activePage;
          return (
            <button
              className={`nav-item ${isActive ? "active" : ""}`}
              type="button"
              key={item.label}
              onClick={() => onNavigate(item.key as PageKey)}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
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
