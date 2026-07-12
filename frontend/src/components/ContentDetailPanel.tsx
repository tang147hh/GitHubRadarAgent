import { ArrowRight, Clipboard, Download, GitCompare, PackageCheck, Pencil, Save, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { deleteManualEdit, fetchContentMarkdown, fetchManualEdit, packageFromManual, saveManualEdit } from "../api";
import { contentStatusLabel, contentTypeLabels, contentVariantLabels, contentVariants } from "../contentDisplay";
import { copyText, downloadMarkdown } from "../fileUtils";
import { useContentIndexData } from "../hooks/useContentIndexData";
import type { Language } from "../i18n";
import { markdownImageSrc } from "../markdownImages";
import type { ContentItem, ContentVariant } from "../types";

export type EditorMode = "preview" | "edit" | "compare";

type EditorProps = {
  mode: EditorMode;
  content: string;
  baseContent: string;
  manualContent: string;
  markdownPath: string;
  language: Language;
  onChange: (value: string) => void;
};

export function ContentEditorPanel({ mode, content, baseContent, manualContent, markdownPath, language, onChange }: EditorProps) {
  const empty = language === "zh" ? "暂无人工修改版" : "No manual edit";
  if (mode === "edit") return <textarea className="content-markdown-editor" value={content} onChange={(event) => onChange(event.target.value)} spellCheck={false} />;
  if (mode === "compare") return <div className="content-compare-grid">
    <section><h3>{language === "zh" ? "AI 版本" : "AI version"}</h3><pre>{baseContent}</pre></section>
    <section><h3>{language === "zh" ? "人工版本" : "Manual version"}</h3><pre>{manualContent || empty}</pre></section>
  </div>;
  return content ? <article className="markdown-preview markdown-body full-markdown content-markdown-preview">
    <ReactMarkdown components={{
      a: ({ href, children, ...props }) => <a {...props} href={href} target={href?.startsWith("http") ? "_blank" : undefined} rel={href?.startsWith("http") ? "noreferrer" : undefined}>{children}</a>,
      img: ({ src, alt, ...props }) => <img {...props} alt={alt || ""} src={markdownImageSrc(src, markdownPath)} />,
    }}>{content}</ReactMarkdown>
  </article> : <p className="empty-state">{empty}</p>;
}

type Props = {
  item: ContentItem | null;
  variant: ContentVariant | null;
  markdownContent: string;
  markdownPath?: string;
  language: Language;
  loading?: boolean;
  error?: string | null;
  initialMode?: EditorMode;
  onClose?: () => void;
  onOpenLibrary?: (contentId: string, variant: ContentVariant) => void;
};

export function ContentDetailPanel({ item, variant, markdownContent, markdownPath = "", language, loading, error, initialMode = "preview", onClose, onOpenLibrary }: Props) {
  const index = useContentIndexData();
  const [mode, setMode] = useState<EditorMode>(initialMode);
  const [activeVariant, setActiveVariant] = useState<ContentVariant>(variant || "source");
  const [content, setContent] = useState(markdownContent);
  const [path, setPath] = useState(markdownPath);
  const [manualContent, setManualContent] = useState("");
  const [baseContent, setBaseContent] = useState("");
  const [basedOn, setBasedOn] = useState<"source" | "publish" | "package">("source");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [localError, setLocalError] = useState("");
  const [copied, setCopied] = useState(false);
  const labels = language === "zh" ? {
    detail: "内容详情", preview: "预览", edit: "编辑内容", compare: "对比版本", save: "保存人工修改版", discard: "放弃修改",
    remove: "删除人工修改版", package: "用人工版生成发布包", copy: "复制当前 Markdown", copied: "已复制", download: "下载当前 Markdown",
    library: "在内容库打开", close: "关闭", quality: "质量分", ready: "可发布", yes: "是", no: "否", based: "基于哪个版本",
    saved: "保存成功，已更新内容库", deleted: "删除成功，已更新内容库", packaged: "发布包已用人工修改版生成，已更新内容库",
  } : {
    detail: "Content detail", preview: "Preview", edit: "Edit content", compare: "Compare versions", save: "Save manual edit", discard: "Discard changes",
    remove: "Delete manual edit", package: "Build package from manual", copy: "Copy current Markdown", copied: "Copied", download: "Download current Markdown",
    library: "Open in Content Library", close: "Close", quality: "Quality", ready: "Publish ready", yes: "Yes", no: "No", based: "Based on variant",
    saved: "Saved and Content Index updated", deleted: "Deleted and Content Index updated", packaged: "Package generated from manual edit and Content Index updated",
  };

  useEffect(() => {
    if (!item) return;
    setActiveVariant(variant || "source"); setContent(markdownContent); setPath(markdownPath); setMessage(""); setLocalError("");
  }, [item?.content_id, markdownContent, markdownPath, variant]);

  const loadManual = async () => {
    if (!item) return "";
    try {
      const manual = await fetchManualEdit(item.content_id);
      setManualContent(manual.content_markdown); setBasedOn(manual.based_on_variant); return manual.content_markdown;
    } catch { setManualContent(""); return ""; }
  };

  const loadVariant = async (next: ContentVariant) => {
    if (!item) return;
    setBusy(true); setLocalError(""); setActiveVariant(next);
    try {
      if (next === "manual") {
        const manual = await fetchManualEdit(item.content_id); setContent(manual.content_markdown); setManualContent(manual.content_markdown); setPath(manual.manual_edit_path);
      } else {
        const result = await fetchContentMarkdown(item.content_id, next); setContent(result.content); setPath(result.path);
      }
    } catch (reason) { setContent(""); setLocalError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const enterEdit = async () => {
    if (!item) return;
    setBusy(true); setLocalError("");
    try {
      const manual = await loadManual();
      if (manual) { setContent(manual); setActiveVariant("manual"); }
      else {
        const fallback: ContentVariant = item.publish_path ? "publish" : "source";
        const result = await fetchContentMarkdown(item.content_id, fallback); setContent(result.content); setPath(result.path); setBasedOn(fallback); setActiveVariant(fallback);
      }
      setMode("edit");
    } catch (reason) { setLocalError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const enterCompare = async () => {
    if (!item) return;
    setBusy(true); setLocalError("");
    try {
      const baseVariant: ContentVariant = item.publish_path ? "publish" : "source";
      const [base] = await Promise.all([fetchContentMarkdown(item.content_id, baseVariant), loadManual()]);
      setBaseContent(base.content); setMode("compare");
    } catch (reason) { setLocalError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (!item) return;
    if (initialMode === "edit") void enterEdit();
    else if (initialMode === "compare") void enterCompare();
    else setMode("preview");
  }, [initialMode, item?.content_id]);

  const mutate = async (action: "save" | "delete" | "package") => {
    if (!item) return;
    setBusy(true); setLocalError(""); setMessage("");
    try {
      if (action === "save") {
        await saveManualEdit(item.content_id, { content_id: item.content_id, content_markdown: content, based_on_variant: basedOn });
        setManualContent(content); setActiveVariant("manual"); setMessage(labels.saved);
      } else if (action === "delete") {
        await deleteManualEdit(item.content_id); setManualContent(""); setMessage(labels.deleted); setMode("preview");
      } else { await packageFromManual(item.content_id); setMessage(labels.packaged); }
      await index.rebuild();
      if (action === "delete") await loadVariant(item.publish_path ? "publish" : "source");
      if (action === "package") await loadVariant("package");
    } catch (reason) { setLocalError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const availableVariants = useMemo(() => contentVariants.filter((entry) => Boolean(item?.[entry.path]) || entry.key === "manual" && Boolean(item?.has_manual_edit)), [item]);
  if (!item && !loading && !error) return null;

  return <section className="panel page-panel content-preview-panel content-detail-panel">
    <div className="panel-header content-preview-header">
      <div><h2>{item?.title || labels.detail}</h2><p>{item ? `${item.content_id} · ${path}` : labels.detail}</p></div>
      <div className="preview-actions">
        {item ? <>
          <button className="secondary-button icon-command" type="button" onClick={() => setMode("preview")}><span>{labels.preview}</span></button>
          <button className="secondary-button icon-command" type="button" onClick={() => void enterEdit()} disabled={busy}><Pencil size={15} /><span>{labels.edit}</span></button>
          <button className="secondary-button icon-command" type="button" onClick={() => void enterCompare()} disabled={busy}><GitCompare size={15} /><span>{labels.compare}</span></button>
        </> : null}
        {onClose ? <button className="icon-button" type="button" title={labels.close} onClick={onClose}><X size={17} /></button> : null}
      </div>
    </div>
    {item ? <>
      <div className="content-preview-meta">
        <span className={`content-kind content-kind-${item.content_type}`}>{contentTypeLabels[language][item.content_type]}</span><span>{item.source}</span><span>{contentStatusLabel(language, item.status)}</span>
        <span>{labels.quality}: <strong>{item.quality_score == null ? "-" : item.quality_score.toFixed(1)}</strong></span><span>{labels.ready}: <strong>{item.publish_ready ? labels.yes : labels.no}</strong></span>
        {item.repo_full_name ? <span>Repo: <strong>{item.repo_full_name}</strong></span> : null}{item.news_ids.length ? <span>News: <strong>{item.news_ids.join(", ")}</strong></span> : null}{item.agent_run_id ? <span>Agent: <strong>{item.agent_run_id}</strong></span> : null}
      </div>
      <details className="content-detail-metadata"><summary>{language === "zh" ? "路径、来源与警告" : "Paths, sources and warnings"}</summary><dl>
        {contentVariants.map((entry) => item[entry.path] ? <div key={entry.key}><dt>{contentVariantLabels[language][entry.key]}</dt><dd>{String(item[entry.path])}</dd></div> : null)}
        {item.source_urls.map((url) => <div key={url}><dt>URL</dt><dd><a href={url} target="_blank" rel="noreferrer">{url}</a></dd></div>)}
        {item.warnings.map((warning, indexValue) => <div key={`${warning}:${indexValue}`}><dt>Warning</dt><dd>{warning}</dd></div>)}
      </dl></details>
      {mode === "preview" ? <div className="content-variant-tabs">{availableVariants.map((entry) => <button key={entry.key} className={activeVariant === entry.key ? "active" : ""} type="button" onClick={() => void loadVariant(entry.key)}>{contentVariantLabels[language][entry.key]}</button>)}</div> : null}
      {mode === "edit" ? <div className="editor-settings"><label>{labels.based}<select value={basedOn} onChange={(event) => setBasedOn(event.target.value as typeof basedOn)}><option value="source">{contentVariantLabels[language].source}</option><option value="publish">{contentVariantLabels[language].publish}</option><option value="package">{contentVariantLabels[language].package}</option></select></label></div> : null}
    </> : null}
    {loading || busy ? <p className="empty-state">...</p> : null}{error || localError ? <div className="banner error">{error || localError}</div> : null}{message ? <div className="banner success">{message}</div> : null}
    {item && !loading && !busy ? <ContentEditorPanel mode={mode} content={content} baseContent={baseContent} manualContent={manualContent} markdownPath={path} language={language} onChange={setContent} /> : null}
    {item ? <div className="content-editor-actions">
      {mode === "edit" ? <><button className="primary-button icon-command" type="button" disabled={busy || !content.trim()} onClick={() => void mutate("save")}><Save size={15} />{labels.save}</button><button className="secondary-button" type="button" onClick={() => { setMode("preview"); void loadVariant(variant || "source"); }}>{labels.discard}</button></> : null}
      {item.has_manual_edit ? <><button className="secondary-button icon-command" type="button" disabled={busy} onClick={() => void mutate("package")}><PackageCheck size={15} />{labels.package}</button><button className="danger-button icon-command" type="button" disabled={busy} onClick={() => void mutate("delete")}><Trash2 size={15} />{labels.remove}</button></> : null}
      {content ? <><button className="secondary-button icon-command" type="button" onClick={() => void copyText(content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); })}><Clipboard size={15} />{copied ? labels.copied : labels.copy}</button><button className="secondary-button icon-command" type="button" onClick={() => downloadMarkdown(`${item.safe_name || item.content_id}_${activeVariant}.md`, content)}><Download size={15} />{labels.download}</button></> : null}
      {onOpenLibrary ? <button className="secondary-button icon-command" type="button" onClick={() => onOpenLibrary(item.content_id, activeVariant)}><ArrowRight size={15} />{labels.library}</button> : null}
    </div> : null}
  </section>;
}
