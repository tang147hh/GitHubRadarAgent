import { Archive, Check, FileText, GitCompare, PackageCheck, Pencil, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ContentPreviewPanel } from "../components/ContentPreviewPanel";
import type { EditorMode } from "../components/ContentDetailPanel";
import { packageFromManual } from "../api";
import { contentStatusLabel, contentTypeLabels, contentVariants, contentVariantLabels } from "../contentDisplay";
import { useContentIndexData } from "../hooks/useContentIndexData";
import type { Language } from "../i18n";
import type { ContentItem, ContentSource, ContentType, ContentVariant, PageKey } from "../types";
import { formatDate } from "./pageUtils";

type LibraryTab = "all" | "github" | "news" | "digest" | "agent" | "manual";
const artifactPathKey = "contentLibraryArtifactPath";

const copy = {
  zh: {
    title: "内容索引", subtitle: "统一查看文章、发布稿、发布包和 Agent 产物。", rebuild: "重建索引",
    tabs: { all: "全部", github: "GitHub 项目文章", news: "AI 新闻文章", digest: "AI 日报", agent: "Agent 产物", manual: "人工修改版" },
    total: "总内容数", publishable: "可发布", packaged: "已打包", types: "内容类型",
    search: "搜索标题", type: "内容类型", status: "状态", ready: "发布状态", source: "来源", manualFilter: "人工修改", edited: "已人工修改", any: "全部", yes: "可发布", no: "不可发布",
    columns: ["标题", "类型", "来源", "状态", "质量分", "可发布", "发布包", "更新时间", "操作"],
    sourceVariant: "查看原文", publishVariant: "查看发布稿", packageVariant: "查看发布包", reportVariant: "查看报告",
    empty: "暂无内容", edit: "编辑", compare: "对比", packageManual: "用人工版生成发布包", emptyManual: "未人工修改", preview: "Markdown 预览", copy: "复制", download: "下载", close: "关闭", copied: "已复制", loading: "正在读取内容索引...",
  },
  en: {
    title: "Content Index", subtitle: "Browse articles, publishing drafts, packages, and Agent artifacts in one place.", rebuild: "Rebuild index",
    tabs: { all: "All", github: "GitHub Articles", news: "AI News Articles", digest: "AI Digest", agent: "Agent Artifacts", manual: "Manual Edits" },
    total: "Total", publishable: "Publishable", packaged: "Packaged", types: "Content types",
    search: "Search titles", type: "Content type", status: "Status", ready: "Publish state", source: "Source", manualFilter: "Manual edit", edited: "Manually edited", any: "All", yes: "Publishable", no: "Not publishable",
    columns: ["Title", "Type", "Source", "Status", "Quality", "Ready", "Package", "Updated", "Actions"],
    sourceVariant: "View source", publishVariant: "View publish draft", packageVariant: "View package", reportVariant: "View report",
    empty: "No content", edit: "Edit", compare: "Compare", packageManual: "Build package from manual", emptyManual: "Not edited", preview: "Markdown preview", copy: "Copy", download: "Download", close: "Close", copied: "Copied", loading: "Loading content index...",
  },
} as const;

function inTab(item: ContentItem, tab: LibraryTab) {
  if (tab === "all") return true;
  if (tab === "github") return item.content_type === "github_article" || item.content_type === "github_custom_article";
  if (tab === "news") return item.content_type === "ai_news_article";
  if (tab === "digest") return item.content_type === "ai_news_digest";
  if (tab === "manual") return item.content_type === "manual_edit" || item.has_manual_edit;
  return item.content_type === "agent_artifact" || item.source === "agent" || Boolean(item.agent_run_id);
}

export function ContentLibraryPage({ language, initialContentId, initialVariant = "source", onInitialContentOpened }: { language: Language; onNavigate?: (page: PageKey) => void; initialContentId?: string | null; initialVariant?: ContentVariant; onInitialContentOpened?: () => void }) {
  const text = copy[language];
  const content = useContentIndexData();
  const { index, items, loading, error, rebuild } = content;
  const [tab, setTab] = useState<LibraryTab>("all");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<ContentType | "all">("all");
  const [status, setStatus] = useState("all");
  const [ready, setReady] = useState<"all" | "yes" | "no">("all");
  const [source, setSource] = useState<ContentSource | "all">("all");
  const [manual, setManual] = useState<"all" | "yes" | "no">("all");
  const [detailMode, setDetailMode] = useState<EditorMode>("preview");
  const statuses = useMemo(() => Array.from(new Set(items.map((item) => item.status))).sort(), [items]);
  const visible = useMemo(() => items.filter((item) => {
    const titleMatches = item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
    return inTab(item, tab) && titleMatches && (type === "all" || item.content_type === type)
      && (status === "all" || item.status === status) && (source === "all" || item.source === source)
      && (ready === "all" || item.publish_ready === (ready === "yes"));
  }).filter((item) => manual === "all" || item.has_manual_edit === (manual === "yes")), [items, manual, query, ready, source, status, tab, type]);

  const openVariant = (item: ContentItem, variant: ContentVariant, mode: EditorMode = "preview") => { setDetailMode(mode); void content.openMarkdown(item.content_id, variant).catch(() => undefined); };
  const buildManualPackage = async (item: ContentItem) => {
    try { await packageFromManual(item.content_id); await content.rebuild(); openVariant(item, "package"); }
    catch { openVariant(item, "manual"); }
  };

  useEffect(() => {
    if (!initialContentId || !items.length) return;
    const item = items.find((candidate) => candidate.content_id === initialContentId);
    if (!item) return;
    setTab(inTab(item, "github") ? "github" : inTab(item, "news") ? "news" : inTab(item, "digest") ? "digest" : inTab(item, "manual") ? "manual" : "agent");
    openVariant(item, initialVariant);
    onInitialContentOpened?.();
  }, [initialContentId, initialVariant, items, onInitialContentOpened]);

  useEffect(() => {
    if (!index) return;
    const artifactPath = sessionStorage.getItem(artifactPathKey);
    if (!artifactPath) return;
    sessionStorage.removeItem(artifactPathKey);
    const normalized = artifactPath.replace(/\\/g, "/").replace(/^.*?\/(outputs|workspace)\//, "$1/");
    for (const item of index.items) {
      const variants: [ContentVariant, string | null | undefined][] = [["source", item.markdown_path], ["publish", item.publish_path], ["package", item.package_path], ["report", item.report_path]];
      const match = variants.find(([, path]) => path === normalized);
      if (match) { setTab("agent"); openVariant(item, match[0]); break; }
    }
  }, [index]);

  const packaged = items.filter((item) => Boolean(item.package_path)).length;
  const publishable = items.filter((item) => item.publish_ready).length;

  return <div className="page-stack content-library-page">
    <section className="panel page-panel">
      <div className="panel-header page-header"><div><h2>{text.title}</h2><p>{text.subtitle}</p></div><button className="secondary-button icon-command" type="button" onClick={() => void rebuild()} disabled={loading}><RefreshCw size={16} className={loading ? "spin-icon" : ""} />{text.rebuild}</button></div>
      <div className="workspace-metrics content-metrics"><div><FileText size={18} /><span>{text.total}</span><strong>{index?.total_count ?? 0}</strong></div><div><Check size={18} /><span>{text.publishable}</span><strong>{publishable}</strong></div><div><PackageCheck size={18} /><span>{text.packaged}</span><strong>{packaged}</strong></div><div><Archive size={18} /><span>{text.types}</span><strong>{Object.values(index?.type_counts || {}).filter(Boolean).length}</strong></div></div>
    </section>
    <section className="panel page-panel">
      <div className="library-tabs" role="tablist">{(Object.keys(text.tabs) as LibraryTab[]).map((key) => <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{text.tabs[key]}</button>)}</div>
      <div className="content-filter-grid"><label className="content-search"><span>{text.search}</span><div><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} /></div></label><label><span>{text.type}</span><select value={type} onChange={(event) => setType(event.target.value as ContentType | "all")}><option value="all">{text.any}</option>{Object.entries(contentTypeLabels[language]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>{text.status}</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">{text.any}</option>{statuses.map((value) => <option key={value} value={value}>{contentStatusLabel(language, value)}</option>)}</select></label><label><span>{text.ready}</span><select value={ready} onChange={(event) => setReady(event.target.value as "all" | "yes" | "no")}><option value="all">{text.any}</option><option value="yes">{text.yes}</option><option value="no">{text.no}</option></select></label><label><span>{text.source}</span><select value={source} onChange={(event) => setSource(event.target.value as ContentSource | "all")}><option value="all">{text.any}</option><option value="github">GitHub</option><option value="ai_news">AI News</option><option value="agent">Agent</option><option value="manual">Manual</option></select></label><label><span>{text.manualFilter}</span><select value={manual} onChange={(event) => setManual(event.target.value as typeof manual)}><option value="all">{text.any}</option><option value="yes">{text.edited}</option><option value="no">{text.emptyManual}</option></select></label></div>
      {error ? <div className="banner error">{error}</div> : null}{index?.warnings.length ? <div className="banner warning">{index.warnings.join("; ")}</div> : null}{loading ? <p className="empty-state">{text.loading}</p> : null}
      {!loading && visible.length ? <div className="table-wrap"><table className="ranking-table data-table library-table"><thead><tr>{text.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{visible.map((item) => <tr key={item.content_id}><td><button className="content-title-button" type="button" onClick={() => openVariant(item, "source")}><strong>{item.title}</strong></button>{item.has_manual_edit ? <small>{text.edited} · {formatDate(item.manual_edit_updated_at || "")}</small> : null}{item.agent_run_id ? <small>Agent: {item.agent_run_id}</small> : null}</td><td><span className={`content-kind content-kind-${item.content_type}`}>{contentTypeLabels[language][item.content_type]}</span></td><td>{item.source}</td><td>{contentStatusLabel(language, item.status)}</td><td>{item.quality_score == null ? "-" : item.quality_score.toFixed(1)}</td><td>{item.publish_ready ? <Check size={16} className="positive-icon" /> : "-"}</td><td>{item.package_path ? <PackageCheck size={16} className="positive-icon" /> : "-"}</td><td>{formatDate(item.manual_edit_updated_at || item.updated_at || item.created_at || item.date)}</td><td><div className="content-row-actions">{contentVariants.map((variant) => item[variant.path] ? <button key={variant.key} type="button" onClick={() => openVariant(item, variant.key)}>{contentVariantLabels[language][variant.key]}</button> : null)}<button type="button" onClick={() => openVariant(item, item.publish_path ? "publish" : "source", "edit")}><Pencil size={13} />{text.edit}</button><button type="button" onClick={() => openVariant(item, "source", "compare")}><GitCompare size={13} />{text.compare}</button>{item.has_manual_edit ? <button type="button" onClick={() => void buildManualPackage(item)}><PackageCheck size={13} />{text.packageManual}</button> : null}</div></td></tr>)}</tbody></table></div> : null}
      {!loading && !visible.length ? <div className="library-empty"><Archive size={28} /><p>{text.empty}</p></div> : null}
    </section>
    <ContentPreviewPanel item={content.selectedItem} variant={content.selectedVariant} markdownContent={content.markdownContent} markdownPath={content.markdownPath} language={language} loading={content.markdownLoading} error={content.markdownError} initialMode={detailMode} onClose={content.closeMarkdown} />
  </div>;
}
