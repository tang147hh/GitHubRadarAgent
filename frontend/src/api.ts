import type {
  CustomArticleMarkdownContent,
  CustomArticleRequest,
  CustomArticleResult,
  DashboardResponse,
  ConfigStatus,
  FinalArticleContent,
  FinalArticleItem,
  JobStatus,
  LatestRunResponse,
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

export const fetchHealth = () => getJson<Record<string, unknown>>("/api/health");
export const fetchConfigStatus = () => getJson<ConfigStatus>("/api/config/status");
export const fetchSettings = () => getJson<SettingsResponse>("/api/settings");
export const saveSettings = (settings: UiSettings) => putJson<SettingsResponse>("/api/settings", settings);
export const resetSettings = () => postJson<SettingsResponse>("/api/settings/reset", {});
export const fetchDashboard = () => getJson<DashboardResponse>("/api/dashboard");
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
