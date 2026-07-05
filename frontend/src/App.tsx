import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createJobEventSource,
  fetchDashboard,
  fetchFinalArticle,
  fetchJob,
  fetchOutputFinalArticle,
  fetchOutputReport,
  fetchOutputs,
  fetchOutputDate,
  fetchSettings,
  runDailyAsync,
} from "./api";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { articlePreview, finalArticles, getLocalized, pipelineStages, reviewSummary, runInfo, scoreRanking, stats } from "./data/mockData";
import { copyText, downloadMarkdown } from "./fileUtils";
import type { Language } from "./i18n";
import { translations } from "./i18n";
import { ArticlesPage } from "./pages/ArticlesPage";
import { CandidatesPage } from "./pages/CandidatesPage";
import { CustomArticlePage } from "./pages/CustomArticlePage";
import { DashboardPage } from "./pages/DashboardPage";
import { ResearchNotesPage } from "./pages/ResearchNotesPage";
import { ReportsPage, type ReportSelection } from "./pages/ReportsPage";
import { ReviewsPage } from "./pages/ReviewsPage";
import { RunsHistoryPage } from "./pages/RunsHistoryPage";
import { ScoreRankingPage } from "./pages/ScoreRankingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TopicAnglesPage } from "./pages/TopicAnglesPage";
import type { DashboardResponse, FinalArticleItem, JobEvent, JobLog, JobStatus, PageKey, PipelineStage, RunDailyParams, UiSettings } from "./types";

type NavigateOptions = {
  date?: string;
  selection?: ReportSelection | null;
};

type PreviewState = {
  title?: string;
  intro?: string;
  markdown?: string;
  projectUrl?: string;
  sourcePath?: string;
};

const defaultRunParams: RunDailyParams = {
  limit_per_keyword: 3,
  score_top: 30,
  research_top: 3,
  article_top: 3,
  review_threshold: 80,
  cooldown_days: 30,
  ignore_history: false,
  allow_recent_fallback: false,
  prefer_growth_projects: true,
};

const orderedStageNames = [
  "discover",
  "score",
  "select-projects",
  "research-selected",
  "angles",
  "plan-content",
  "write-articles",
  "review-articles",
  "package-articles",
];

function createPendingStages(): PipelineStage[] {
  return orderedStageNames.map((name) => ({
    name,
    status: "pending",
    message: "",
    error: null,
    started_at: null,
    finished_at: null,
  }));
}

function createMockDashboard(language: Language): DashboardResponse {
  return {
    health: {
      github_token_configured: true,
      llm_configured: true,
      last_run_status: runInfo.status,
    },
    stats: {
      today_candidates: stats.todayCandidates,
      top_scored_projects: stats.topScoredProjects,
      final_articles: stats.finalArticles,
      review_pass_rate: stats.reviewPassRate,
    },
    run_info: {
      run_id: runInfo.runId,
      status: runInfo.status,
      duration: runInfo.duration,
      output: runInfo.output,
    },
    pipeline: pipelineStages.map((stage) => ({
      name: stage === "write" ? "write-articles" : stage === "review" ? "review-articles" : stage,
      status: "success",
    })),
    score_ranking: scoreRanking.map((project, index) => ({
      rank: project.rank || index + 1,
      full_name: project.project,
      html_url: `https://github.com/${project.project}`,
      stars: project.stars,
      total_score: project.score,
      language: project.language,
      status: project.status,
    })),
    final_articles: finalArticles.map((article) => ({
      title: getLocalized(article.title, language),
      full_name: article.project,
      safe_name: article.project.replace("/", "__"),
      word_count: article.words,
      review_score: article.reviewScore,
      html_url: `https://github.com/${article.project}`,
    })),
    review_summary: {
      total_count: 1,
      pass_count: 1,
      pass_rate: stats.reviewPassRate,
      warnings: [],
      reviews: [
        {
          full_name: "langgenius/dify",
          title: getLocalized(articlePreview.title, language),
          total_score: 89,
          factual_score: 28,
          title_score: 18,
          structure_score: 18,
          readability_score: 13,
          completeness_score: 14,
          issues: reviewSummary.factualWarnings[language],
          pass_review: true,
        },
      ],
    },
  };
}

function mockPreview(language: Language): PreviewState {
  return {
    title: getLocalized(articlePreview.title, language),
    intro: getLocalized(articlePreview.intro, language),
    markdown: getLocalized(articlePreview.markdown, language),
    projectUrl: articlePreview.projectUrl,
    sourcePath: "mockData.ts",
  };
}

function fileNameForArticle(article: FinalArticleItem) {
  return `${article.safe_name || (article.full_name || article.project || "final_article").replace("/", "__")}.md`;
}

function eventToLog(event: JobEvent): JobLog {
  return {
    time: event.time,
    stage: event.stage,
    type: event.type,
    message: event.message || event.error || event.type,
  };
}

function updateStagesWithEvent(stages: PipelineStage[], event: JobEvent): PipelineStage[] {
  if (!event.stage) return stages;
  return stages.map((stage) => {
    if (stage.name !== event.stage) return stage;
    if (event.type === "stage_started") {
      return {
        ...stage,
        status: "running",
        message: event.message || stage.message,
        error: null,
        started_at: event.time || stage.started_at,
      };
    }
    if (event.type === "stage_succeeded") {
      return {
        ...stage,
        status: "success",
        message: event.message || stage.message,
        error: null,
        finished_at: event.time || stage.finished_at,
      };
    }
    if (event.type === "stage_failed") {
      return {
        ...stage,
        status: "failed",
        message: event.message || stage.message,
        error: event.error || event.message || stage.error,
        finished_at: event.time || stage.finished_at,
      };
    }
    return stage;
  });
}

function runInfoFromJob(job: JobStatus | null) {
  if (!job) return undefined;
  return {
    run_id: job.result?.run_id ? String(job.result.run_id) : job.job_id,
    status: job.status,
    duration: job.started_at && job.finished_at ? undefined : null,
    output: job.result?.output_dir ? String(job.result.output_dir) : null,
  };
}

function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [selectedArticle, setSelectedArticle] = useState<FinalArticleItem | null>(null);
  const [selectedArticleMarkdown, setSelectedArticleMarkdown] = useState<string>("");
  const [preview, setPreview] = useState<PreviewState>(() => mockPreview("zh"));
  const [loading, setLoading] = useState(false);
  const [loadingArticle, setLoadingArticle] = useState<string | null>(null);
  const [error, setError] = useState<string>("");
  const [isRunning, setIsRunning] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [liveStages, setLiveStages] = useState<PipelineStage[]>(() => createPendingStages());
  const [liveLogs, setLiveLogs] = useState<JobLog[]>([]);
  const [runError, setRunError] = useState("");
  const [lastRunMessage, setLastRunMessage] = useState("");
  const [useMockFallback, setUseMockFallback] = useState(false);
  const [runParams, setRunParams] = useState<RunDailyParams>(defaultRunParams);
  const [uiSettings, setUiSettings] = useState<UiSettings | null>(null);
  const [selectedOutputDate, setSelectedOutputDate] = useState("");
  const [selectedOutputSelection, setSelectedOutputSelection] = useState<ReportSelection | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollingRef = useRef<number | null>(null);
  const t = useMemo(() => translations[language], [language]);
  const fallbackDashboard = useMemo(() => createMockDashboard(language), [language]);
  const activeDashboard = dashboard || fallbackDashboard;
  const pageTitle = t.pageTitles[activePage];
  const pageSubtitle = t.pageSubtitles[activePage];

  const refreshDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchDashboard();
      setDashboard(response);
      setUseMockFallback(false);
      setError("");
    } catch (err) {
      setDashboard(null);
      setUseMockFallback(true);
      setError(err instanceof Error ? err.message : "Backend API is unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshDashboard();
  }, [refreshDashboard]);

  const applyUiSettings = useCallback((settings: UiSettings) => {
    setUiSettings(settings);
    setRunParams(settings.run_defaults);
    setLanguage(settings.frontend.default_language);
  }, []);

  useEffect(() => {
    fetchSettings()
      .then((response) => applyUiSettings(response.settings))
      .catch(() => {
        setUiSettings(null);
        setRunParams(defaultRunParams);
      });
  }, [applyUiSettings]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!selectedArticle && useMockFallback) {
      setPreview(mockPreview(language));
      setSelectedArticleMarkdown(getLocalized(articlePreview.markdown, language));
    }
  }, [language, selectedArticle, useMockFallback]);

  const statsValues = {
    todayCandidates: activeDashboard.stats?.today_candidates ?? 0,
    topScoredProjects: activeDashboard.stats?.top_scored_projects ?? 0,
    finalArticles: activeDashboard.stats?.final_articles ?? 0,
    reviewPassRate: activeDashboard.stats?.review_pass_rate ?? "0%",
  };

  const statuses = {
    github: activeDashboard.health?.github_token_configured ? t.status.githubValue : t.status.notConfigured,
    llm: activeDashboard.health?.llm_configured ? t.status.llmValue : t.status.notConfigured,
    lastRun: isRunning ? t.status.running : activeDashboard.health?.last_run_status || t.status.unknown,
  };

  const showActionMessage = (message: string) => {
    setLastRunMessage(message);
    window.setTimeout(() => {
      setLastRunMessage((current) => (current === message ? "" : current));
    }, 3500);
  };

  const handleNavigate = useCallback((page: PageKey, options?: NavigateOptions) => {
    if (page === "reports") {
      if (options?.date) setSelectedOutputDate(options.date);
      setSelectedOutputSelection(options?.selection || null);
    }
    setActivePage(page);
  }, []);

  const clearPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  const finishJob = useCallback(
    async (status: "success" | "failed", errorMessage?: string) => {
      setIsRunning(false);
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      clearPolling();
      if (status === "failed") {
        const message = errorMessage || t.messages.runFailed;
        setRunError(message);
        showActionMessage(message);
        return;
      }
      setRunError("");
      showActionMessage(t.messages.jobRefreshed);
      await refreshDashboard();
    },
    [refreshDashboard, t.messages.jobRefreshed, t.messages.runFailed],
  );

  const applyJobStatus = useCallback(
    async (job: JobStatus) => {
      setJobStatus(job);
      if (job.stages?.length) {
        setLiveStages(job.stages);
      }
      if (job.logs?.length) {
        setLiveLogs(job.logs);
      }
      if (job.status === "success") {
        await finishJob("success");
      } else if (job.status === "failed") {
        await finishJob("failed", job.error || undefined);
      } else {
        setIsRunning(true);
      }
    },
    [finishJob],
  );

  const startPollingJob = useCallback(
    (jobId: string) => {
      clearPolling();
      pollingRef.current = window.setInterval(() => {
        void fetchJob(jobId)
          .then((job) => applyJobStatus(job))
          .catch((err) => {
            setRunError(err instanceof Error ? err.message : t.messages.runFailed);
          });
      }, 2000);
    },
    [applyJobStatus, t.messages.runFailed],
  );

  const loadArticleMarkdown = async (article: FinalArticleItem) => {
    if (useMockFallback || !article.safe_name) {
      const markdown = getLocalized(articlePreview.markdown, language);
      setSelectedArticle(article);
      setSelectedArticleMarkdown(markdown);
      setPreview({
        title: article.title || getLocalized(articlePreview.title, language),
        intro: article.summary || getLocalized(articlePreview.intro, language),
        markdown,
        projectUrl: article.html_url || articlePreview.projectUrl,
        sourcePath: "mockData.ts",
      });
      return markdown;
    }

    setLoadingArticle(article.safe_name);
    try {
      const content = await fetchFinalArticle(article.safe_name);
      const markdown = content.content_markdown || "";
      setSelectedArticle(article);
      setSelectedArticleMarkdown(markdown);
      setPreview({
        title: article.title || article.full_name || article.safe_name,
        intro: article.summary,
        markdown,
        projectUrl: article.html_url,
        sourcePath: content.path,
      });
      return markdown;
    } catch (err) {
      showActionMessage(err instanceof Error ? err.message : t.messages.previewFailed);
      return "";
    } finally {
      setLoadingArticle(null);
    }
  };

  const handleDownload = async (article: FinalArticleItem) => {
    const markdown =
      selectedArticle?.safe_name === article.safe_name && selectedArticleMarkdown
        ? selectedArticleMarkdown
        : await loadArticleMarkdown(article);
    if (!markdown) return;

    downloadMarkdown(fileNameForArticle(article), markdown);
  };

  const handleRunDaily = async () => {
    if (useMockFallback) {
      showActionMessage(t.messages.backendUnavailable);
      return;
    }
    setIsRunning(true);
    setRunError("");
    setJobStatus(null);
    setActiveJobId(null);
    setLiveStages(createPendingStages());
    setLiveLogs([]);
    setLastRunMessage(t.messages.connectingProgress);
    eventSourceRef.current?.close();
    clearPolling();
    try {
      const result = await runDailyAsync({
        ...runParams,
        daily_keywords: uiSettings?.discovery.daily_keywords,
      });
      setActiveJobId(result.job_id);
      setJobStatus({ job_id: result.job_id, status: result.status, stages: createPendingStages(), logs: [] });
      const source = createJobEventSource(result.job_id);
      eventSourceRef.current = source;

      source.addEventListener("progress", (message) => {
        const event = JSON.parse((message as MessageEvent).data) as JobEvent;
        setLiveStages((current) => updateStagesWithEvent(current, event));
        setLiveLogs((current) => [...current, eventToLog(event)].slice(-300));
        setJobStatus((current) =>
          current
            ? {
                ...current,
                status:
                  event.type === "run_succeeded"
                    ? "success"
                    : event.type === "run_failed" || event.type === "stage_failed"
                      ? "failed"
                      : event.type === "run_started" || event.type === "stage_started"
                        ? "running"
                        : current.status,
                current_stage:
                  event.type === "stage_started"
                    ? event.stage || current.current_stage
                    : event.type === "run_succeeded" || event.type === "run_failed" || event.type === "stage_failed"
                      ? null
                      : current.current_stage,
                error: event.error || current.error,
                result: event.result || current.result,
              }
            : current,
        );
      });

      source.addEventListener("done", () => {
        void finishJob("success");
      });

      source.addEventListener("error", (message) => {
        const data = (message as MessageEvent).data;
        if (data) {
          try {
            const payload = JSON.parse(data) as { error?: string };
            void finishJob("failed", payload.error);
            return;
          } catch {
            // Fall through to polling fallback for transport-shaped errors.
          }
        }
        source.close();
        eventSourceRef.current = null;
        showActionMessage(t.messages.pollingFallback);
        startPollingJob(result.job_id);
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : t.messages.runFailed;
      setRunError(message);
      showActionMessage(message);
      setIsRunning(false);
    }
  };

  const openLatestOutput = async (selection: ReportSelection) => {
    if (useMockFallback) {
      setPreview(mockPreview(language));
      setSelectedArticleMarkdown(getLocalized(articlePreview.markdown, language));
      showActionMessage(t.messages.backendUnavailable);
      return;
    }
    try {
      const payload = await fetchOutputs();
      const date = payload.dates?.[0]?.date;
      if (!date) {
        showActionMessage(t.empty.noOutputs);
        return;
      }
      handleNavigate("reports", { date, selection });
    } catch (err) {
      showActionMessage(err instanceof Error ? err.message : t.messages.reportFailed);
    }
  };

  const handleOpenFinalArticles = async () => {
    if (useMockFallback) {
      showActionMessage(t.messages.backendUnavailable);
      return;
    }
    try {
      const payload = await fetchOutputs();
      const date = payload.dates?.[0]?.date;
      if (!date) {
        showActionMessage(t.empty.noOutputs);
        return;
      }
      const detail = await fetchOutputDate(date);
      const firstFinal = detail.final_articles?.[0];
      handleNavigate("reports", {
        date,
        selection: firstFinal ? { type: "final_article", safeName: firstFinal.safe_name } : { type: "report", name: "final_articles_index" },
      });
    } catch (err) {
      showActionMessage(err instanceof Error ? err.message : t.messages.reportFailed);
    }
  };

  const handleCopyLatestMarkdown = async () => {
    let markdown = "";
    if (useMockFallback) {
      markdown = selectedArticleMarkdown || getLocalized(articlePreview.markdown, language);
    } else {
      try {
        const payload = await fetchOutputs();
        const date = payload.dates?.[0]?.date;
        if (date) {
          const detail = await fetchOutputDate(date);
          const firstFinal = detail.final_articles?.[0];
          const content = firstFinal
            ? await fetchOutputFinalArticle(date, firstFinal.safe_name)
            : await fetchOutputReport(date, "final_articles_index");
          markdown = content.content_markdown || "";
        }
      } catch (err) {
        showActionMessage(err instanceof Error ? err.message : t.messages.copyFailed);
        return;
      }
    }
    if (!markdown) {
      showActionMessage(t.messages.copyFailed);
      return;
    }
    try {
      const copied = await copyText(markdown);
      showActionMessage(copied ? t.messages.copySuccess : t.messages.copyFailed);
    } catch {
      showActionMessage(t.messages.copyFailed);
    }
  };

  const renderActivePage = () => {
    if (activePage === "customArticle") return <CustomArticlePage t={t} language={language} />;
    if (activePage === "candidates") return <CandidatesPage t={t} />;
    if (activePage === "scoreRanking") return <ScoreRankingPage t={t} />;
    if (activePage === "researchNotes") return <ResearchNotesPage t={t} />;
    if (activePage === "topicAngles") return <TopicAnglesPage t={t} />;
    if (activePage === "articles") return <ArticlesPage t={t} language={language} />;
    if (activePage === "reports") {
      return <ReportsPage t={t} initialDate={selectedOutputDate} initialSelection={selectedOutputSelection} />;
    }
    if (activePage === "reviews") return <ReviewsPage t={t} />;
    if (activePage === "runsHistory") return <RunsHistoryPage t={t} onViewOutputs={(date) => handleNavigate("reports", { date })} />;
    if (activePage === "settings") {
      return (
        <SettingsPage
          t={t}
          language={language}
          runParams={runParams}
          settings={uiSettings}
          onSettingsChange={applyUiSettings}
        />
      );
    }

    return (
      <DashboardPage
        t={t}
        language={language}
        dashboard={activeDashboard}
        preview={preview}
        useMockFallback={useMockFallback}
        error={error}
        runError={runError}
        statsValues={statsValues}
        isRunning={isRunning}
        activeJobId={activeJobId}
        jobStatus={jobStatus}
        liveStages={liveStages}
        liveLogs={liveLogs}
        runParams={runParams}
        setRunParams={setRunParams}
        loadingArticle={loadingArticle}
        lastRunMessage={lastRunMessage}
        onRunDaily={handleRunDaily}
        onOpenFinalArticles={() => void handleOpenFinalArticles()}
        onViewScoreReport={() => void openLatestOutput({ type: "report", name: "score_report" })}
        onCopyLatestMarkdown={() => void handleCopyLatestMarkdown()}
        onPreviewArticle={(article) => void loadArticleMarkdown(article)}
        onDownloadArticle={(article) => void handleDownload(article)}
        runInfoFromJob={runInfoFromJob}
      />
    );
  };

  return (
    <div className="app-shell">
      <Sidebar t={t} activePage={activePage} onNavigate={handleNavigate} />
      <div className="main-shell">
        <TopBar
          t={t}
          language={language}
          onLanguageChange={setLanguage}
          title={pageTitle}
          subtitle={pageSubtitle}
          statuses={statuses}
          onRefresh={refreshDashboard}
          loading={loading}
        />
        <main className="dashboard">
          {renderActivePage()}
        </main>
      </div>
    </div>
  );
}

export default App;
