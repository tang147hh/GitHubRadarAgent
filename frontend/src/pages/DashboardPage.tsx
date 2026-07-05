import { CheckCircle2, FileCheck2, Gauge, ListFilter, ShieldCheck } from "lucide-react";
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
}: DashboardPageProps) {
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
