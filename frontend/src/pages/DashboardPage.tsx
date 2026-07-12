import { ArrowRight, CheckCircle2, FileCheck2, Gauge, ListFilter, PackageCheck, Pencil, Send, ShieldCheck } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { ArticlePreview } from "../components/ArticlePreview";
import { FinalArticles } from "../components/FinalArticles";
import { PipelineProgress } from "../components/PipelineProgress";
import { QuickActions } from "../components/QuickActions";
import { ReviewSummary } from "../components/ReviewSummary";
import { RunLogs } from "../components/RunLogs";
import { ScoreRanking } from "../components/ScoreRanking";
import { StatCard } from "../components/StatCard";
import type { Language, Translation } from "../i18n";
import type {
  DashboardResponse,
  FinalArticleItem,
  JobLog,
  JobStatus,
  PipelineStage,
  RunDailyParams,
} from "../types";
import { useContentIndexData } from "../hooks/useContentIndexData";

type PreviewState = {
  title?: string;
  intro?: string;
  markdown?: string;
  projectUrl?: string;
  sourcePath?: string;
};

type DashboardPageProps = {
  t: Translation;
  language: Language;
  dashboard: DashboardResponse;
  preview: PreviewState;
  useMockFallback: boolean;
  error: string;
  runError: string;
  statsValues: {
    todayCandidates: number;
    topScoredProjects: number;
    finalArticles: number;
    reviewPassRate: string | number;
  };
  isRunning: boolean;
  activeJobId: string | null;
  jobStatus: JobStatus | null;
  liveStages: PipelineStage[];
  liveLogs: JobLog[];
  runParams: RunDailyParams;
  setRunParams: Dispatch<SetStateAction<RunDailyParams>>;
  loadingArticle: string | null;
  lastRunMessage: string;
  onRunDaily: () => void;
  onOpenFinalArticles: () => void;
  onViewScoreReport: () => void;
  onCopyLatestMarkdown: () => void;
  onPreviewArticle: (article: FinalArticleItem) => void;
  onDownloadArticle: (article: FinalArticleItem) => void;
  runInfoFromJob: (job: JobStatus | null) => DashboardResponse["run_info"] | undefined;
  onOpenPublishingDesk: () => void;
};

export function DashboardPage({
  t,
  language,
  dashboard,
  preview,
  useMockFallback,
  error,
  runError,
  statsValues,
  isRunning,
  activeJobId,
  jobStatus,
  liveStages,
  liveLogs,
  runParams,
  setRunParams,
  loadingArticle,
  lastRunMessage,
  onRunDaily,
  onOpenFinalArticles,
  onViewScoreReport,
  onCopyLatestMarkdown,
  onPreviewArticle,
  onDownloadArticle,
  runInfoFromJob,
  onOpenPublishingDesk,
}: DashboardPageProps) {
  const content = useContentIndexData();
  const publishing = language === "zh" ? { title: "发布概览", ready: "今日可发布内容", package: "待打包", low: "质量偏低", manual: "有人工修改版", open: "打开发布工作台" } : { title: "Publishing overview", ready: "Ready today", package: "Needs package", low: "Quality low", manual: "Manual edits", open: "Open Publishing Desk" };
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const readyToday = content.items.filter((item) => item.date === today && item.readiness_status === "ready").length;
  return (
    <>
      {useMockFallback ? <div className="banner warning">{t.messages.backendUnavailable}</div> : null}
      {error ? <div className="banner error">{error}</div> : null}
      {runError ? <div className="banner error">{runError}</div> : null}

      <div className="stats-grid">
        <StatCard label={t.stats.todayCandidates} value={statsValues.todayCandidates} icon={ListFilter} tone="blue" />
        <StatCard label={t.stats.topScoredProjects} value={statsValues.topScoredProjects} icon={CheckCircle2} tone="green" />
        <StatCard label={t.stats.finalArticles} value={statsValues.finalArticles} icon={FileCheck2} tone="amber" />
        <StatCard label={t.stats.reviewPassRate} value={statsValues.reviewPassRate} icon={ShieldCheck} tone="violet" />
        <StatCard label={t.stats.averageQualityScore} value={dashboard.stats?.average_quality_score ?? 0} icon={Gauge} tone="blue" />
      </div>

      <section className="panel page-panel dashboard-publishing-overview">
        <div className="panel-header"><h2>{publishing.title}</h2><button className="secondary-button icon-command" type="button" onClick={onOpenPublishingDesk}><Send size={15} />{publishing.open}<ArrowRight size={15} /></button></div>
        <div className="publishing-summary-strip"><div><CheckCircle2 size={17} /><span>{publishing.ready}</span><strong>{readyToday}</strong></div><div><PackageCheck size={17} /><span>{publishing.package}</span><strong>{content.index?.needs_package_count ?? 0}</strong></div><div><Gauge size={17} /><span>{publishing.low}</span><strong>{content.index?.quality_low_count ?? 0}</strong></div><div><Pencil size={17} /><span>{publishing.manual}</span><strong>{content.index?.manual_edit_count ?? 0}</strong></div></div>
      </section>

      <div className="dashboard-row top-panels">
        <PipelineProgress
          t={t}
          stages={isRunning || activeJobId ? liveStages : dashboard.pipeline || []}
          runInfo={isRunning || activeJobId ? runInfoFromJob(jobStatus) : dashboard.run_info}
          currentStage={jobStatus?.current_stage}
        />
        <QuickActions
          t={t}
          params={runParams}
          onParamsChange={setRunParams}
          onRunDaily={onRunDaily}
          onOpenFinalArticles={onOpenFinalArticles}
          onViewScoreReport={onViewScoreReport}
          onCopyLatestMarkdown={onCopyLatestMarkdown}
          isRunning={isRunning}
          disabled={useMockFallback}
          message={lastRunMessage}
        />
      </div>

      <RunLogs t={t} logs={liveLogs} activeJobId={activeJobId} />

      <div className="dashboard-row lower-panels">
        <ScoreRanking t={t} items={dashboard.score_ranking || []} />
        <FinalArticles
          t={t}
          language={language}
          articles={dashboard.final_articles || []}
          onPreview={onPreviewArticle}
          onDownload={onDownloadArticle}
          loadingArticle={loadingArticle}
        />
      </div>

      <div className="dashboard-row lower-panels">
        <ArticlePreview t={t} language={language} loading={Boolean(loadingArticle)} {...preview} />
        <ReviewSummary t={t} language={language} summary={dashboard.review_summary} />
      </div>
    </>
  );
}
