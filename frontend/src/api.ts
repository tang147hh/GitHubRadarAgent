import type {
  CustomArticleMarkdownContent,
  CustomArticleRequest,
  CustomArticleResult,
  DashboardResponse,
  ConfigStatus,
  FinalArticleContent,
  FinalArticleItem,
  JobStatus,
  NewsArticle,
  NewsArticleListResponse,
  NewsArticleQualityReport,
  LatestRunResponse,
  NewsArticlePlan,
  NewsArticlePlanRequest,
  NewsArticleReviewRequest,
  NewsArticleWriteRequest,
  NewsCollectRequest,
  NewsCollectionResult,
  NewsDetailResult,
  NewsDigestArticle,
  NewsDigestReviewRequest,
  NewsDigestWriteRequest,
  NewsEventBuildRequest,
  NewsEventResult,
  NewsScoreRequest,
  NewsScoringResult,
  NewsReportContent,
  NewsSelectionContext,
  NewsSelectionRequest,
  OutputDateDetail,
  OutputDateSummary,
  OutputMarkdownContent,
  PackageArticlesRequest,
  PackageArticlesResponse,
  ReportContent,
  SettingsResponse,
  RunDailyAsyncResponse,
  RunDailyAsyncParams,
  RunDailyParams,
  RunDailyResponse,
  RunsResponse,
  SnapshotName,
  UiSettings,
  AgentRun,
  AgentRunApprovalRequest,
  AgentRunRequest,
  ContentIndex,
  ContentItem,
  ContentMarkdown,
  ContentVariant,
  ManualEdit,
  ManualEditRequest,
  PackageMissingResult,
  PublishingDesk,
  PublishingExport,
} from "./types";

const viteEnv = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env;

export const API_BASE_URL = (viteEnv?.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = payload.detail ?? payload.message;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    // Fall back to the HTTP status text below.
  }
  return response.statusText || "Request failed";
}

export async function getJson<T>(path: string): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`);
    if (!response.ok) {
      throw new ApiError(await parseErrorMessage(response), response.status);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error instanceof Error ? error.message : "Backend API is unavailable");
  }
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new ApiError(await parseErrorMessage(response), response.status);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error instanceof Error ? error.message : "Backend API is unavailable");
  }
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new ApiError(await parseErrorMessage(response), response.status);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error instanceof Error ? error.message : "Backend API is unavailable");
  }
}

export async function deleteJson<T>(path: string): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { method: "DELETE" });
    if (!response.ok) throw new ApiError(await parseErrorMessage(response), response.status);
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error instanceof Error ? error.message : "Backend API is unavailable");
  }
}

export const fetchHealth = () => getJson<Record<string, unknown>>("/api/health");
export const fetchConfigStatus = () => getJson<ConfigStatus>("/api/config/status");
export const fetchSettings = () => getJson<SettingsResponse>("/api/settings");
export const saveSettings = (settings: UiSettings) => putJson<SettingsResponse>("/api/settings", settings);
export const resetSettings = () => postJson<SettingsResponse>("/api/settings/reset", {});
export const fetchDashboard = () => getJson<DashboardResponse>("/api/dashboard");
export const startAgentRun = (request: AgentRunRequest) => postJson<AgentRun>("/api/agent/runs", request);
export const fetchLatestAgentRun = () => getJson<AgentRun>("/api/agent/runs/latest");
export const fetchAgentRun = (runId: string) => getJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}`);
export const approveAgentRun = (runId: string, request: AgentRunApprovalRequest) =>
  postJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}/approve`, request);
export const resumeAgentRun = (runId: string) =>
  postJson<AgentRun>(`/api/agent/runs/${encodeURIComponent(runId)}/resume`, {});
export const fetchLatestNews = () => getJson<NewsCollectionResult>("/api/news/latest");
export const fetchNewsReport = () => getJson<NewsReportContent>("/api/news/report");
export const collectNews = (request: NewsCollectRequest) => postJson<NewsCollectionResult>("/api/news/collect", request);
export const fetchNewsDetail = (newsId: string) => getJson<NewsDetailResult>(`/api/news/items/${encodeURIComponent(newsId)}`);
export const refreshNewsDetail = (newsId: string) =>
  postJson<NewsDetailResult>(`/api/news/items/${encodeURIComponent(newsId)}/refresh`, {});
export const createNewsSelection = (request: NewsSelectionRequest) =>
  postJson<NewsSelectionContext>("/api/news/selections", request);
export const fetchLatestNewsSelection = () => getJson<NewsSelectionContext>("/api/news/selections/latest");
export const fetchNewsSelection = (selectionId: string) =>
  getJson<NewsSelectionContext>(`/api/news/selections/${encodeURIComponent(selectionId)}`);
export const createNewsArticlePlan = (request: NewsArticlePlanRequest) =>
  postJson<NewsArticlePlan>("/api/news/article-plan", request);
export const fetchLatestNewsArticlePlan = () => getJson<NewsArticlePlan>("/api/news/article-plan/latest");
export const fetchNewsArticlePlan = (planId: string) =>
  getJson<NewsArticlePlan>(`/api/news/article-plan/${encodeURIComponent(planId)}`);
export const writeNewsArticle = (request: NewsArticleWriteRequest) =>
  postJson<NewsArticle>("/api/news/article/write", request);
export const reviewNewsArticle = (request: NewsArticleReviewRequest) =>
  postJson<NewsArticle>("/api/news/article/review", request);
export const fetchLatestNewsArticle = () => getJson<NewsArticle>("/api/news/article/latest");
export const fetchLatestNewsArticleContent = () => getJson<NewsReportContent>("/api/news/article/latest/content");
export const fetchLatestNewsArticleReport = () => getJson<NewsReportContent>("/api/news/article/latest/report");
export const fetchLatestNewsArticleReview = () =>
  getJson<(NewsArticleQualityReport & { exists?: boolean; quality_report?: NewsArticleQualityReport | null; message?: string })>(
    "/api/news/article/review/latest",
  );
export const fetchLatestNewsArticlePublish = () => getJson<NewsReportContent>("/api/news/article/latest/publish");
export const fetchLatestNewsArticlePackage = () => getJson<NewsReportContent>("/api/news/article/latest/package");
export const fetchNewsArticles = () => getJson<NewsArticleListResponse>("/api/news/articles");
export const fetchNewsArticle = (articleId: string) =>
  getJson<NewsArticle>(`/api/news/article/${encodeURIComponent(articleId)}`);
export const fetchNewsArticleContent = (articleId: string) =>
  getJson<NewsReportContent>(`/api/news/article/${encodeURIComponent(articleId)}/content`);
export const fetchNewsArticleReport = (articleId: string) =>
  getJson<NewsReportContent>(`/api/news/article/${encodeURIComponent(articleId)}/report`);
export const fetchNewsArticleReview = (articleId: string) =>
  getJson<(NewsArticleQualityReport & { exists?: boolean; quality_report?: NewsArticleQualityReport | null; message?: string })>(
    `/api/news/article/${encodeURIComponent(articleId)}/review`,
  );
export const fetchNewsArticlePublish = (articleId: string) =>
  getJson<NewsReportContent>(`/api/news/article/${encodeURIComponent(articleId)}/publish`);
export const fetchNewsArticlePackage = (articleId: string) =>
  getJson<NewsReportContent>(`/api/news/article/${encodeURIComponent(articleId)}/package`);
export const fetchNewsScores = () => getJson<NewsScoringResult>("/api/news/scores");
export const scoreNews = (request: NewsScoreRequest) => postJson<NewsScoringResult>("/api/news/score", request);
export const fetchNewsScoresReport = () => getJson<NewsReportContent>("/api/news/scores/report");
export const fetchNewsEvents = () => getJson<NewsEventResult>("/api/news/events");
export const fetchNewsEventsReport = () => getJson<NewsReportContent>("/api/news/events/report");
export const buildNewsEvents = (request: NewsEventBuildRequest) =>
  postJson<NewsEventResult>("/api/news/events/build", request);
export const fetchNewsDigest = () => getJson<NewsDigestArticle>("/api/news/digest");
export const fetchNewsDigestContent = () => getJson<NewsReportContent>("/api/news/digest/content");
export const writeNewsDigest = (request: NewsDigestWriteRequest) =>
  postJson<NewsDigestArticle>("/api/news/digest/write", request);
export const reviewNewsDigest = (request: NewsDigestReviewRequest) =>
  postJson<NewsDigestArticle>("/api/news/digest/review", request);
export const fetchNewsDigestReview = () => getJson<NewsDigestArticle>("/api/news/digest/review");
export const fetchNewsDigestPackage = () => getJson<NewsReportContent>("/api/news/digest/package");
export const fetchSnapshot = <T = unknown>(name: SnapshotName) =>
  getJson<T>(`/api/snapshots/${encodeURIComponent(name)}`);
export const fetchFinalArticles = () => getJson<{ articles?: FinalArticleItem[] }>("/api/articles/final");
export const fetchFinalArticle = (safeName: string, source?: string) =>
  getJson<FinalArticleContent>(
    `/api/articles/final/${encodeURIComponent(safeName)}${source ? `?source=${encodeURIComponent(source)}` : ""}`,
  );
export const fetchPackagedArticle = (safeName: string, source?: string) =>
  getJson<FinalArticleContent>(
    `/api/articles/package/${encodeURIComponent(safeName)}${source ? `?source=${encodeURIComponent(source)}` : ""}`,
  );
export const packageArticles = (params: PackageArticlesRequest) =>
  postJson<PackageArticlesResponse>("/api/articles/package", params);
export const fetchReport = (reportName: string) =>
  getJson<ReportContent>(`/api/reports/${encodeURIComponent(reportName)}`);
export const fetchOutputs = () => getJson<{ dates: OutputDateSummary[] }>("/api/outputs");
export const fetchOutputDate = (date: string) => getJson<OutputDateDetail>(`/api/outputs/${encodeURIComponent(date)}`);
export const fetchOutputReport = (date: string, reportName: string) =>
  getJson<OutputMarkdownContent>(`/api/outputs/${encodeURIComponent(date)}/reports/${encodeURIComponent(reportName)}`);
export const fetchOutputFinalArticle = (date: string, safeName: string) =>
  getJson<OutputMarkdownContent>(`/api/outputs/${encodeURIComponent(date)}/final-articles/${encodeURIComponent(safeName)}`);
export const fetchOutputPackage = (date: string, safeName: string) =>
  getJson<OutputMarkdownContent>(`/api/outputs/${encodeURIComponent(date)}/packages/${encodeURIComponent(safeName)}`);
export const fetchOutputArticle = (date: string, safeName: string) =>
  getJson<OutputMarkdownContent>(`/api/outputs/${encodeURIComponent(date)}/articles/${encodeURIComponent(safeName)}`);
export const fetchRuns = () => getJson<RunsResponse>("/api/runs");
export const fetchLatestRun = () => getJson<LatestRunResponse>("/api/runs/latest");
export const runDaily = (params: RunDailyParams) => postJson<RunDailyResponse>("/api/run-daily", params);
export const runDailyAsync = (params: RunDailyAsyncParams) =>
  postJson<RunDailyAsyncResponse>("/api/run-daily/async", params);
export const runCustomArticleAsync = (params: CustomArticleRequest) =>
  postJson<RunDailyAsyncResponse>("/api/custom-articles/async", params);
export const fetchLatestCustomArticle = () => getJson<CustomArticleResult>("/api/custom-articles/latest");
export const fetchLatestCustomArticleContent = () =>
  getJson<CustomArticleMarkdownContent>("/api/custom-articles/latest/content");
export const fetchLatestCustomArticleReport = () =>
  getJson<CustomArticleMarkdownContent>("/api/custom-articles/latest/report");
export const fetchLatestCustomArticlePackage = () =>
  getJson<CustomArticleMarkdownContent>("/api/custom-articles/latest/package");
export const fetchJob = (jobId: string) => getJson<JobStatus>(`/api/jobs/${encodeURIComponent(jobId)}`);
export const fetchJobs = () => getJson<{ jobs: JobStatus[] }>("/api/jobs");
export const createJobEventSource = (jobId: string) =>
  new EventSource(`${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}/events`);

export const fetchContentIndex = () => getJson<ContentIndex>("/api/content");
export const rebuildContentIndex = () => postJson<ContentIndex>("/api/content/rebuild", {});
export const fetchContentItem = (contentId: string) =>
  getJson<ContentItem>(`/api/content/${encodeURIComponent(contentId)}`);
export const fetchContentMarkdown = (contentId: string, variant: ContentVariant) =>
  getJson<ContentMarkdown>(
    `/api/content/${encodeURIComponent(contentId)}/markdown?variant=${encodeURIComponent(variant)}`,
  );
export const fetchContentIndexReport = () => getJson<ContentMarkdown>("/api/content/report");
export const fetchManualEdit = (contentId: string) =>
  getJson<ManualEdit>(`/api/content/${encodeURIComponent(contentId)}/manual-edit`);
export const saveManualEdit = (contentId: string, request: ManualEditRequest) =>
  putJson<Omit<ManualEdit, "content_markdown">>(`/api/content/${encodeURIComponent(contentId)}/manual-edit`, request);
export const deleteManualEdit = (contentId: string) =>
  deleteJson<{ content_id: string; deleted: boolean }>(`/api/content/${encodeURIComponent(contentId)}/manual-edit`);
export const packageFromManual = (contentId: string) =>
  postJson<{ content_id: string; package_path: string; manual_edit_path: string; generated_at: string }>(
    `/api/content/${encodeURIComponent(contentId)}/package-from-manual`, {},
  );
export const fetchPublishingDesk = () => getJson<PublishingDesk>("/api/publishing/desk");
export const rebuildPublishingDesk = () => postJson<PublishingDesk>("/api/publishing/rebuild", {});
export const packageMissingPublishingContent = () =>
  postJson<PackageMissingResult>("/api/publishing/package-missing", {});
export const fetchPublishingExport = (contentId: string) =>
  getJson<PublishingExport>(`/api/publishing/export/${encodeURIComponent(contentId)}`);
