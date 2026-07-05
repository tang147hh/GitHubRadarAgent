import ReactMarkdown from "react-markdown";
import { Copy, Download, FileText, LoaderCircle, PackagePlus, Play, RefreshCw, ShieldCheck, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createJobEventSource,
  fetchJob,
  fetchLatestCustomArticle,
  fetchLatestCustomArticleContent,
  fetchLatestCustomArticlePackage,
  fetchLatestCustomArticleReport,
  packageArticles,
  runCustomArticleAsync,
} from "../api";
import { PipelineProgress } from "../components/PipelineProgress";
import { RunLogs } from "../components/RunLogs";
import type { Language, Translation } from "../i18n";
import { markdownImageSrc } from "../markdownImages";
import type { CustomArticleResult, JobEvent, JobLog, JobStatus, PipelineStage } from "../types";
import { copyText, downloadMarkdown, extractTitleFromMarkdown, safeFilename } from "./pageUtils";

type CustomArticlePageProps = {
  t: Translation;
  language: Language;
};

type PreviewTab = "article" | "package" | "report";

const customStageNames = [
  "parse_repo",
  "research",
  "parse_direction",
  "analyze_style_reference",
  "plan_content",
  "write_article",
  "review",
  "humanize",
  "polish",
  "originality",
  "package",
  "done",
];

function createCustomStages(): PipelineStage[] {
  return customStageNames.map((name) => ({
    name,
    status: "pending",
    message: "",
    error: null,
    started_at: null,
    finished_at: null,
  }));
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
      return { ...stage, status: "running", message: event.message || "", error: null, started_at: event.time || stage.started_at };
    }
    if (event.type === "stage_succeeded") {
      return { ...stage, status: "success", message: event.message || "", error: null, finished_at: event.time || stage.finished_at };
    }
    if (event.type === "stage_failed") {
      return {
        ...stage,
        status: "failed",
        message: event.message || "",
        error: event.error || event.message || stage.error,
        finished_at: event.time || stage.finished_at,
      };
    }
    return stage;
  });
}

function normalizeSourceName(fileName: string, index: number) {
  const name = fileName.trim();
  return name || `reference_file_${index}`;
}

export function CustomArticlePage({ t, language }: CustomArticlePageProps) {
  const [repoUrl, setRepoUrl] = useState("https://github.com/sharkdp/bat");
  const [direction, setDirection] = useState("");
  const [referenceText, setReferenceText] = useState("");
  const [fileReferences, setFileReferences] = useState<{ name: string; text: string }[]>([]);
  const [activeTab, setActiveTab] = useState<PreviewTab>("article");
  const [articleMarkdown, setArticleMarkdown] = useState("");
  const [packageMarkdown, setPackageMarkdown] = useState("");
  const [reportMarkdown, setReportMarkdown] = useState("");
  const [latestResult, setLatestResult] = useState<CustomArticleResult | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isPackaging, setIsPackaging] = useState(false);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [stages, setStages] = useState<PipelineStage[]>(() => createCustomStages());
  const [logs, setLogs] = useState<JobLog[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollingRef = useRef<number | null>(null);

  const copy = t.customArticle;
  const currentMarkdown = activeTab === "article" ? articleMarkdown : activeTab === "package" ? packageMarkdown : reportMarkdown;
  const currentPath =
    activeTab === "article"
      ? latestResult?.output_markdown_path
      : activeTab === "package"
        ? latestResult?.package_path || latestResult?.packaged_article_path
        : latestResult?.report_path;
  const originalityReport = latestResult?.originality_report;
  const originalityChecked = Boolean(latestResult?.originality_checked || originalityReport?.checked);
  const originalityPassed = Boolean(latestResult?.originality_passed ?? originalityReport?.passed);
  const originalityStatusText = originalityChecked
    ? originalityPassed
      ? copy.originalityPassed
      : copy.originalityFailed
    : copy.originalityNotChecked;
  const originalityBadgeClass = originalityChecked ? (originalityPassed ? "" : "failed") : "pending";
  const similarityRisk =
    typeof originalityReport?.similarity_score === "number" ? originalityReport.similarity_score.toFixed(4) : "-";
  const originalityIssues = originalityReport?.issues || [];
  const previewTitle = useMemo(() => {
    const title = extractTitleFromMarkdown(currentMarkdown);
    if (title) return title;
    if (activeTab === "article") return copy.articlePreview;
    if (activeTab === "package") return copy.packagePreview;
    return copy.reportPreview;
  }, [activeTab, copy.articlePreview, copy.packagePreview, copy.reportPreview, currentMarkdown]);

  const clearPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  const loadLatest = useCallback(async () => {
    try {
      const [result, article, articlePackage, report] = await Promise.all([
        fetchLatestCustomArticle(),
        fetchLatestCustomArticleContent(),
        fetchLatestCustomArticlePackage(),
        fetchLatestCustomArticleReport(),
      ]);
      setLatestResult(result.exists ? result : null);
      setArticleMarkdown(article.content_markdown || "");
      setPackageMarkdown(articlePackage.content_markdown || "");
      setReportMarkdown(report.content_markdown || "");
      if (!result.exists) {
        setMessage(result.message || copy.emptyLatest);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.loadFailed);
    }
  }, [copy.emptyLatest, copy.loadFailed]);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      clearPolling();
    };
  }, []);

  const finishJob = useCallback(
    async (status: "success" | "failed", errorMessage?: string) => {
      setIsRunning(false);
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      clearPolling();
      if (status === "failed") {
        setError(errorMessage || copy.runFailed);
        setMessage("");
        return;
      }
      setError("");
      setMessage(copy.runSuccess);
      await loadLatest();
      setActiveTab("article");
    },
    [copy.runFailed, copy.runSuccess, loadLatest],
  );

  const applyJobStatus = useCallback(
    async (job: JobStatus) => {
      setJobStatus(job);
      if (job.stages?.length) setStages(job.stages);
      if (job.logs?.length) setLogs(job.logs);
      if (job.status === "success") await finishJob("success");
      else if (job.status === "failed") await finishJob("failed", job.error || undefined);
      else setIsRunning(true);
    },
    [finishJob],
  );

  const startPollingJob = useCallback(
    (jobId: string) => {
      clearPolling();
      pollingRef.current = window.setInterval(() => {
        void fetchJob(jobId)
          .then((job) => applyJobStatus(job))
          .catch((err) => setError(err instanceof Error ? err.message : copy.runFailed));
      }, 2000);
    },
    [applyJobStatus, copy.runFailed],
  );

  const handleFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    const accepted = files.filter((file) => /\.(md|txt)$/i.test(file.name));
    if (!accepted.length) {
      setError(copy.fileTypeError);
      return;
    }
    try {
      const loaded = await Promise.all(
        accepted.slice(0, 4).map(async (file, index) => ({
          name: normalizeSourceName(file.name, index + 1),
          text: await file.text(),
        })),
      );
      setFileReferences(loaded.filter((item) => item.text.trim()));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.fileReadFailed);
    } finally {
      event.target.value = "";
    }
  };

  const handleRun = async () => {
    const trimmedRepoUrl = repoUrl.trim();
    if (!trimmedRepoUrl) {
      setError(copy.repoRequired);
      return;
    }
    const references = [
      ...(referenceText.trim() ? [{ name: copy.pastedReferenceName, text: referenceText.trim() }] : []),
      ...fileReferences.map((item) => ({ name: item.name, text: item.text.trim() })).filter((item) => item.text),
    ];

    setIsRunning(true);
    setError("");
    setMessage(copy.connectingProgress);
    setActiveJobId(null);
    setJobStatus(null);
    setStages(createCustomStages());
    setLogs([]);
    eventSourceRef.current?.close();
    clearPolling();

    try {
      const result = await runCustomArticleAsync({
        repo_url: trimmedRepoUrl,
        direction: direction.trim(),
        reference_texts: references.map((item) => item.text),
        reference_source_names: references.map((item) => item.name),
      });
      setActiveJobId(result.job_id);
      setJobStatus({ job_id: result.job_id, status: result.status, stages: createCustomStages(), logs: [] });
      const source = createJobEventSource(result.job_id);
      eventSourceRef.current = source;

      source.addEventListener("progress", (messageEvent) => {
        const event = JSON.parse((messageEvent as MessageEvent).data) as JobEvent;
        setStages((current) => updateStagesWithEvent(current, event));
        setLogs((current) => [...current, eventToLog(event)].slice(-300));
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
                    : event.type === "stage_succeeded" || event.type === "run_succeeded" || event.type === "run_failed"
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

      source.addEventListener("error", (messageEvent) => {
        const data = (messageEvent as MessageEvent).data;
        if (data) {
          try {
            const payload = JSON.parse(data) as { error?: string };
            void finishJob("failed", payload.error);
            return;
          } catch {
            // Browser transport errors fall back to polling below.
          }
        }
        source.close();
        eventSourceRef.current = null;
        setMessage(copy.pollingFallback);
        startPollingJob(result.job_id);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.runFailed);
      setMessage("");
      setIsRunning(false);
    }
  };

  const handleCopy = async () => {
    if (!currentMarkdown) {
      setMessage(copy.noMarkdown);
      return;
    }
    const copied = await copyText(currentMarkdown);
    setMessage(copied ? copy.copySuccess : copy.copyFailed);
  };

  const handleDownload = () => {
    if (!currentMarkdown) {
      setMessage(copy.noMarkdown);
      return;
    }
    const baseName =
      latestResult?.full_name?.replace("/", "__") || safeFilename(repoUrl.replace(/^https?:\/\/github\.com\//, "")) || "custom_article";
    const suffix = activeTab === "article" ? "" : activeTab === "package" ? "_packaged" : "_report";
    downloadMarkdown(`${baseName}${suffix}.md`, currentMarkdown);
  };

  const handleGeneratePackage = async () => {
    if (!latestResult?.full_name && !latestResult?.final_article?.full_name) {
      setError(copy.emptyLatest);
      return;
    }
    const fullName = latestResult.full_name || latestResult.final_article?.full_name || "";
    const safeName = fullName.replace("/", "__");
    setIsPackaging(true);
    try {
      await packageArticles({ safe_names: [safeName], full_names: [fullName] });
      await loadLatest();
      setActiveTab("package");
      setMessage(t.messages.packageSuccess);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.loadFailed);
    } finally {
      setIsPackaging(false);
    }
  };

  return (
    <div className="custom-article-page">
      {error ? <div className="banner error">{error}</div> : null}
      {message ? <div className="banner success">{message}</div> : null}

      <div className="custom-article-layout">
        <section className="panel custom-input-panel">
          <div className="panel-header">
            <h2>{copy.inputTitle}</h2>
            <span className={`soft-badge ${isRunning ? "running" : "pending"}`}>
              {isRunning ? copy.runningBadge : copy.readyBadge}
            </span>
          </div>

          <div className="custom-form">
            <label>
              <span>{copy.githubUrl}</span>
              <input
                value={repoUrl}
                onChange={(event) => setRepoUrl(event.target.value)}
                placeholder={copy.githubUrlPlaceholder}
                disabled={isRunning}
              />
            </label>
            <label>
              <span>{copy.direction}</span>
              <textarea
                value={direction}
                onChange={(event) => setDirection(event.target.value)}
                placeholder={copy.directionPlaceholder}
                rows={4}
                disabled={isRunning}
              />
            </label>
            <label>
              <span>{copy.referenceText}</span>
              <textarea
                value={referenceText}
                onChange={(event) => setReferenceText(event.target.value)}
                placeholder={copy.referenceTextPlaceholder}
                rows={8}
                disabled={isRunning}
              />
            </label>
            <p className="custom-help">{copy.referenceNotice}</p>

            <label className="file-upload-box">
              <Upload size={17} aria-hidden="true" />
              <span>{copy.uploadReference}</span>
              <input type="file" accept=".md,.txt,text/markdown,text/plain" multiple onChange={handleFiles} disabled={isRunning} />
            </label>

            {fileReferences.length ? (
              <div className="uploaded-list">
                {fileReferences.map((file) => (
                  <span className="soft-badge unknown" key={file.name}>
                    <FileText size={14} aria-hidden="true" />
                    {file.name}
                  </span>
                ))}
              </div>
            ) : null}

            <button className="primary-button full" type="button" onClick={() => void handleRun()} disabled={isRunning}>
              {isRunning ? <LoaderCircle className="spin-icon" size={17} aria-hidden="true" /> : <Play size={17} aria-hidden="true" />}
              <span>{isRunning ? copy.running : copy.run}</span>
            </button>
          </div>
        </section>

        <div className="custom-progress-stack">
          <PipelineProgress
            t={t}
            stages={stages}
            currentStage={jobStatus?.current_stage}
            runInfo={{
              run_id: activeJobId || latestResult?.full_name || "",
              status: jobStatus?.status || latestResult?.status || "pending",
              output: latestResult?.output_markdown_path || null,
            }}
          />
          <RunLogs t={t} logs={logs} activeJobId={activeJobId} />
        </div>
      </div>

      <section className="panel custom-preview-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{copy.outputTitle}</h2>
            <p>{currentPath || copy.outputHint}</p>
          </div>
          <div className="row-actions wrap-actions">
            <button className="secondary-button" type="button" onClick={() => void loadLatest()} disabled={isRunning}>
              <RefreshCw size={16} aria-hidden="true" />
              <span>{copy.refreshLatest}</span>
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => void handleGeneratePackage()}
              disabled={isRunning || isPackaging || !latestResult}
            >
              {isPackaging ? <RefreshCw size={16} aria-hidden="true" /> : <PackagePlus size={16} aria-hidden="true" />}
              <span>
                {isPackaging
                  ? t.actions.generatingPackage
                  : latestResult?.packaged_article_available
                    ? t.actions.regeneratePackage
                    : t.actions.generatePackage}
              </span>
            </button>
            <button className="secondary-button" type="button" onClick={() => void handleCopy()} disabled={!currentMarkdown}>
              <Copy size={16} aria-hidden="true" />
              <span>{copy.copyMarkdown}</span>
            </button>
            <button className="secondary-button" type="button" onClick={handleDownload} disabled={!currentMarkdown}>
              <Download size={16} aria-hidden="true" />
              <span>{copy.downloadMarkdown}</span>
            </button>
          </div>
        </div>

        {latestResult ? (
          <div className="originality-card">
            <div className="originality-card-heading">
              <div className="originality-icon">
                <ShieldCheck size={18} aria-hidden="true" />
              </div>
              <div>
                <h3>{copy.originalityTitle}</h3>
                <p>{copy.originalitySubtitle}</p>
              </div>
              <span className={`soft-badge ${originalityBadgeClass}`}>{originalityStatusText}</span>
            </div>
            <div className="originality-metrics">
              <div>
                <span>{copy.similarityRisk}</span>
                <strong>{similarityRisk}</strong>
              </div>
              <div>
                <span>{copy.rewriteAttempted}</span>
                <strong>{originalityReport?.rewrite_attempted ? copy.yes : copy.no}</strong>
              </div>
            </div>
            <div className="originality-issues">
              <span>{copy.originalityIssues}</span>
              {originalityIssues.length ? (
                <ul>
                  {originalityIssues.slice(0, 4).map((issue, index) => (
                    <li key={`${issue.issue_type || "issue"}-${index}`}>
                      <strong>{issue.severity || "-"}</strong>
                      {issue.description || issue.recommendation || "-"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{originalityReport?.summary || copy.noOriginalityIssues}</p>
              )}
            </div>
          </div>
        ) : null}

        <div className="segmented-tabs" role="tablist" aria-label={copy.outputTitle}>
          <button className={activeTab === "article" ? "active" : ""} type="button" onClick={() => setActiveTab("article")}>
            {copy.articlePreview}
          </button>
          <button className={activeTab === "package" ? "active" : ""} type="button" onClick={() => setActiveTab("package")}>
            {copy.packagePreview}
          </button>
          <button className={activeTab === "report" ? "active" : ""} type="button" onClick={() => setActiveTab("report")}>
            {copy.reportPreview}
          </button>
        </div>

        <article className="markdown-preview markdown-body custom-reading-area">
          <h3>{previewTitle}</h3>
          {currentMarkdown ? (
            <ReactMarkdown
              components={{
                img: ({ src, alt, ...props }) => (
                  <img {...props} alt={alt || ""} src={markdownImageSrc(src, currentPath || "")} />
                ),
              }}
            >
              {currentMarkdown}
            </ReactMarkdown>
          ) : (
            <p className="empty-state">{language === "zh" ? copy.emptyArticle : copy.emptyArticle}</p>
          )}
        </article>
      </section>
    </div>
  );
}
