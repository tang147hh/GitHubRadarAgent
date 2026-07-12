import { ArrowRight } from "lucide-react";
import type { Language, Translation } from "../i18n";
import type { ContentVariant, PageKey } from "../types";
import { ContentWorkspaceList } from "../components/ContentWorkspaceList";
import { AINewsPage } from "./AINewsPage";

export function AINewsWorkbenchPage({ t, onNavigate }: { t: Translation; onNavigate: (page: PageKey) => void }) {
  const actions: Array<{ page: PageKey; label: string }> = [
    { page: "ai-news-collect", label: t.nav.aiNewsCollect },
    { page: "ai-news-list", label: t.nav.aiNewsList },
    { page: "ai-news-selection", label: t.nav.aiNewsSelection },
    { page: "ai-news-digest", label: t.nav.aiNewsDigest },
  ];
  return <div className="page-stack"><AINewsPage t={t} view="workbench" /><section className="panel page-panel workspace-actions"><div className="panel-header"><h2>{t.nav.aiNewsGroup}</h2></div><div>{actions.map((action) => <button className="workspace-link" type="button" key={action.page} onClick={() => onNavigate(action.page)}><span>{action.label}</span><ArrowRight size={16} /></button>)}</div></section></div>;
}
export function AINewsCollectPage({ t }: { t: Translation }) { return <AINewsPage t={t} view="collect" />; }
export function AINewsListPage({ t }: { t: Translation }) { return <AINewsPage t={t} view="list" />; }
export function AINewsDetailPage({ t }: { t: Translation }) { return <AINewsPage t={t} view="detail" />; }
export function AINewsSelectionPage({ t }: { t: Translation }) { return <AINewsPage t={t} view="selection" />; }
export function AINewsPlanPage({ t }: { t: Translation }) { return <AINewsPage t={t} view="plan" />; }
type ContentPageProps = { t: Translation; language: Language; onOpenLibrary: (contentId: string, variant: ContentVariant) => void };
export function AINewsArticlesPage({ t, language, onOpenLibrary }: ContentPageProps) {
  return <div className="page-stack"><ContentWorkspaceList language={language} title={t.nav.aiNewsArticles} types={["ai_news_article"]} mode="news" onOpenLibrary={onOpenLibrary} /><AINewsPage t={t} view="articles" /></div>;
}
export function AINewsDigestPage({ t, language, onOpenLibrary }: ContentPageProps) {
  return <div className="page-stack"><ContentWorkspaceList language={language} title={t.nav.aiNewsDigest} types={["ai_news_digest"]} mode="digest" onOpenLibrary={onOpenLibrary} /><AINewsPage t={t} view="digest" /></div>;
}
export function AINewsReportsPage({ t }: { t: Translation }) { return <AINewsPage t={t} view="reports" />; }
