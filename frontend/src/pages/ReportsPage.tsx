import { Copy, Download, Eye, FileText } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  fetchOutputArticle,
  fetchOutputDate,
  fetchOutputFinalArticle,
  fetchOutputPackage,
  fetchOutputReport,
  fetchOutputs,
} from "../api";
import { copyText, downloadMarkdown, extractTitleFromMarkdown } from "../fileUtils";
import type { Translation } from "../i18n";
import { markdownImageSrc } from "../markdownImages";
import type { OutputDateDetail, OutputDateSummary, OutputFileItem, OutputReportItem } from "../types";

export type ReportSelection =
  | { type: "report"; name: string }
  | { type: "article"; safeName: string }
  | { type: "final_article"; safeName: string }
  | { type: "package"; safeName: string };

type ReportsPageProps = {
  t: Translation;
  initialDate?: string;
  initialSelection?: ReportSelection | null;
};

type ListedFile = {
  id: string;
  type: ReportSelection["type"];
  reportName?: string;
  safeName?: string;
  filename: string;
  title?: string;
  path: string;
  sizeBytes?: number;
};

function formatSize(bytes?: number) {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function reportToFile(report: OutputReportItem): ListedFile {
  return {
    id: `report:${report.name}`,
    type: "report",
    reportName: report.name,
    filename: report.filename,
    title: report.name,
    path: report.path,
    sizeBytes: report.size_bytes,
  };
}

function articleToFile(type: "article" | "final_article" | "package", item: OutputFileItem): ListedFile {
  return {
    id: `${type}:${item.safe_name}`,
    type,
    safeName: item.safe_name,
    filename: item.filename,
    title: item.title,
    path: item.path,
    sizeBytes: item.size_bytes,
  };
}

function selectionId(selection?: ReportSelection | null) {
  if (!selection) return "";
  if (selection.type === "report") return `report:${selection.name}`;
  return `${selection.type}:${selection.safeName}`;
}

export function ReportsPage({ t, initialDate, initialSelection }: ReportsPageProps) {
  const [dates, setDates] = useState<OutputDateSummary[]>([]);
  const [selectedDate, setSelectedDate] = useState(initialDate || "");
  const [detail, setDetail] = useState<OutputDateDetail | null>(null);
  const [selectedFile, setSelectedFile] = useState<ListedFile | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [loadingDates, setLoadingDates] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingMarkdown, setLoadingMarkdown] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const autoLoadedKeyRef = useRef("");

  const groups = useMemo(() => {
    const reports = (detail?.reports || []).filter((report) => report.exists).map(reportToFile);
    const draftArticles = (detail?.articles || []).map((item) => articleToFile("article", item));
    const finalArticles = (detail?.final_articles || []).map((item) => articleToFile("final_article", item));
    const packages = (detail?.packages || []).map((item) => articleToFile("package", item));
    return { reports, draftArticles, finalArticles, packages };
  }, [detail]);

  const allFiles = useMemo(
    () => [...groups.reports, ...groups.packages, ...groups.draftArticles, ...groups.finalArticles],
    [groups],
  );

  const flash = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage((current) => (current === text ? "" : current)), 2500);
  };

  const loadFile = useCallback(
    async (file: ListedFile) => {
      if (!selectedDate) return "";
      setLoadingMarkdown(true);
      try {
        const payload =
          file.type === "report"
            ? await fetchOutputReport(selectedDate, file.reportName || "")
            : file.type === "final_article"
              ? await fetchOutputFinalArticle(selectedDate, file.safeName || "")
              : file.type === "package"
                ? await fetchOutputPackage(selectedDate, file.safeName || "")
                : await fetchOutputArticle(selectedDate, file.safeName || "");
        const nextMarkdown = payload.content_markdown || "";
        setSelectedFile({
          ...file,
          title: file.title || extractTitleFromMarkdown(nextMarkdown),
          path: payload.path || file.path,
        });
        setMarkdown(nextMarkdown);
        setSourcePath(payload.path || file.path);
        setError("");
        return nextMarkdown;
      } catch (err) {
        const text = err instanceof Error ? err.message : t.messages.reportFailed;
        setError(text);
        return "";
      } finally {
        setLoadingMarkdown(false);
      }
    },
    [selectedDate, t.messages.reportFailed],
  );

  useEffect(() => {
    let cancelled = false;
    setLoadingDates(true);
    fetchOutputs()
      .then((payload) => {
        if (cancelled) return;
        const nextDates = payload.dates || [];
        setDates(nextDates);
        setSelectedDate((current) => initialDate || current || nextDates[0]?.date || "");
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : t.messages.reportFailed);
      })
      .finally(() => {
        if (!cancelled) setLoadingDates(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialDate, t.messages.reportFailed]);

  useEffect(() => {
    autoLoadedKeyRef.current = "";
    if (!selectedDate) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    setMarkdown("");
    setSourcePath("");
    fetchOutputDate(selectedDate)
      .then((payload) => {
        if (cancelled) return;
        setDetail(payload);
        setSelectedFile(null);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) {
          setDetail(null);
          setError(err instanceof Error ? err.message : t.messages.reportFailed);
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDate, t.messages.reportFailed]);

  useEffect(() => {
    if (!allFiles.length || loadingDetail) return;
    const preferredId = selectionId(initialSelection);
    const nextFile = allFiles.find((file) => file.id === preferredId) || allFiles[0];
    const autoLoadKey = `${selectedDate}:${preferredId}:${allFiles.map((file) => file.id).join("|")}`;
    if (nextFile && autoLoadedKeyRef.current !== autoLoadKey) {
      autoLoadedKeyRef.current = autoLoadKey;
      void loadFile(nextFile);
    }
  }, [allFiles, initialSelection, loadFile, loadingDetail, selectedDate]);

  const handleCopy = async (content = markdown) => {
    const copied = content ? await copyText(content) : false;
    flash(copied ? t.messages.copySuccess : t.messages.copyFailed);
  };

  const handleDownload = (file = selectedFile, content = markdown) => {
    if (!file || !content) {
      flash(t.messages.downloadFailed);
      return;
    }
    downloadMarkdown(file.filename, content);
  };

  const handleFileCopy = async (file: ListedFile) => {
    const content = selectedFile?.id === file.id && markdown ? markdown : await loadFile(file);
    await handleCopy(content);
  };

  const handleFileDownload = async (file: ListedFile) => {
    const content = selectedFile?.id === file.id && markdown ? markdown : await loadFile(file);
    handleDownload(file, content);
  };

  const renderFileGroup = (title: string, files: ListedFile[]) => (
    <section className="file-group" key={title}>
      <h3>{title}</h3>
      {files.length ? (
        <div className="file-list">
          {files.map((file) => (
            <article className={`file-row ${selectedFile?.id === file.id ? "active" : ""}`} key={file.id}>
              <button className="file-main" type="button" onClick={() => void loadFile(file)}>
                <strong>{file.title || file.filename}</strong>
                <span>{file.filename} · {formatSize(file.sizeBytes)}</span>
              </button>
              <div className="row-actions">
                <button className="icon-button" type="button" onClick={() => void loadFile(file)} title={t.actions.view} aria-label={t.actions.view}>
                  <Eye size={15} aria-hidden="true" />
                </button>
                <button className="icon-button" type="button" onClick={() => void handleFileCopy(file)} title={t.actions.copy} aria-label={t.actions.copy}>
                  <Copy size={15} aria-hidden="true" />
                </button>
                <button className="icon-button" type="button" onClick={() => void handleFileDownload(file)} title={t.actions.download} aria-label={t.actions.download}>
                  <Download size={15} aria-hidden="true" />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="empty-state">{t.empty.noData}</p>
      )}
    </section>
  );

  return (
    <div className="reports-layout">
      <section className="panel reports-dates-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.sections.outputDates}</h2>
            <p>{t.pageSubtitles.reports}</p>
          </div>
        </div>
        {loadingDates ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {!loadingDates && dates.length === 0 ? <p className="empty-state">{t.empty.noOutputs}</p> : null}
        <div className="side-list">
          {dates.map((item) => (
            <button
              className={`side-list-item ${item.date === selectedDate ? "active" : ""}`}
              type="button"
              key={item.date}
              onClick={() => setSelectedDate(item.date)}
            >
              <strong>{item.date}</strong>
              <span>{item.reports.length} {t.sections.reports} · {item.final_articles_count} {t.sections.finalArticles} · {item.packages_count || 0} {t.sections.packages}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel reports-files-panel">
        <div className="panel-header">
          <h2>{selectedDate || t.nav.reports}</h2>
          {loadingDetail ? <span className="soft-badge running">{t.actions.loading}</span> : null}
        </div>
        {error ? <div className="banner error">{error}</div> : null}
        {renderFileGroup(t.sections.reports, groups.reports)}
        {renderFileGroup(t.sections.packages, groups.packages)}
        {renderFileGroup(t.sections.draftArticles, groups.draftArticles)}
        {renderFileGroup(t.sections.finalArticles, groups.finalArticles)}
      </section>

      <section className="panel reports-preview-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{selectedFile?.title || selectedFile?.filename || t.sections.markdownPreview}</h2>
            <p>{sourcePath || t.empty.selectFile}</p>
          </div>
          <div className="row-actions wrap-actions">
            <button className="icon-text-button" type="button" onClick={() => void handleCopy()} disabled={!markdown}>
              <Copy size={16} aria-hidden="true" />
              <span>{t.actions.copy}</span>
            </button>
            <button className="icon-text-button" type="button" onClick={() => handleDownload()} disabled={!markdown}>
              <Download size={16} aria-hidden="true" />
              <span>{t.actions.download}</span>
            </button>
          </div>
        </div>
        {message ? <div className="banner success">{message}</div> : null}
        {loadingMarkdown ? <p className="empty-state">{t.actions.loading}</p> : null}
        <article className="markdown-preview markdown-body full-markdown">
          {markdown ? (
            <ReactMarkdown
              components={{
                img: ({ src, alt, ...props }) => (
                  <img {...props} alt={alt || ""} src={markdownImageSrc(src, sourcePath, selectedDate)} />
                ),
              }}
            >
              {markdown}
            </ReactMarkdown>
          ) : (
            <p className="empty-state">{t.empty.selectFile}</p>
          )}
        </article>
      </section>
    </div>
  );
}
