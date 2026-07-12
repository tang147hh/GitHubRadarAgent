import {
  Check, Clipboard, Download, ExternalLink, FileCheck2, FileQuestion, FileText, Gauge,
  PackageCheck, Pencil, RefreshCw, Search, Sparkles, UserRoundCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { packageFromManual, packageMissingPublishingContent, rebuildPublishingDesk, fetchPublishingDesk } from "../api";
import { ContentPreviewPanel } from "../components/ContentPreviewPanel";
import type { EditorMode } from "../components/ContentDetailPanel";
import { contentTypeLabels } from "../contentDisplay";
import { copyText, downloadMarkdown } from "../fileUtils";
import { useContentIndexData } from "../hooks/useContentIndexData";
import type { Language } from "../i18n";
import { exportContentMarkdown, getBestPublishVariant } from "../publishing";
import type { ContentItem, ContentType, ContentVariant, PublishingDesk, ReadinessStatus } from "../types";
import { formatDate } from "./pageUtils";

const statusOrder: ReadinessStatus[] = ["ready", "needs_review", "needs_package", "needs_manual_edit", "quality_low", "missing_content", "unknown"];
const publishingTypes: ContentType[] = ["github_article", "github_custom_article", "ai_news_article", "ai_news_digest", "agent_artifact"];

const copy = {
  zh: {
    title: "发布工作台", subtitle: "集中处理发布前评估、人工修改、打包与 Markdown 导出。", ready: "可发布", review: "待评估", package: "待打包", low: "质量偏低", manual: "有人工修改版", total: "总内容数",
    rebuild: "重建发布状态", packageMissing: "为缺少发布包内容生成发布包", copyReady: "复制可发布内容清单", exportIndex: "导出可发布内容索引 Markdown",
    search: "搜索标题", type: "内容类型", status: "发布状态", manualFilter: "人工修改", packageFilter: "发布包", readyFilter: "是否可发布", all: "全部", yes: "是", no: "否",
    columns: ["标题", "类型", "状态", "质量分", "人工修改", "发布包", "Agent Run", "更新时间", "下一步建议", "操作"],
    detail: "打开详情", edit: "编辑", publishDraft: "查看发布稿", viewPackage: "查看发布包", export: "导出发布 Markdown", packageManual: "用人工版生成发布包", library: "在内容库打开",
    noData: "没有符合条件的发布内容。", loading: "正在读取发布状态...", copied: "已复制可发布内容清单", exportDone: "已导出", used: "最佳发布版本", hasSource: "原文链接", warning: "warning", partial: "批量打包完成",
  },
  en: {
    title: "Publishing Desk", subtitle: "Review, edit, package, and export content before publishing.", ready: "Ready", review: "Needs review", package: "Needs package", low: "Quality low", manual: "Manual edits", total: "Total content",
    rebuild: "Rebuild publishing status", packageMissing: "Build missing publishing packages", copyReady: "Copy ready content list", exportIndex: "Export ready content index Markdown",
    search: "Search titles", type: "Content type", status: "Publishing status", manualFilter: "Manual edit", packageFilter: "Package", readyFilter: "Publish ready", all: "All", yes: "Yes", no: "No",
    columns: ["Title", "Type", "Status", "Quality", "Manual", "Package", "Agent Run", "Updated", "Next action", "Actions"],
    detail: "Open details", edit: "Edit", publishDraft: "View publish draft", viewPackage: "View package", export: "Export publish Markdown", packageManual: "Build package from manual", library: "Open in Content Library",
    noData: "No publishing content matches these filters.", loading: "Loading publishing status...", copied: "Ready content list copied", exportDone: "Exported", used: "Best publish variant", hasSource: "Source links", warning: "warning(s)", partial: "Batch packaging finished",
  },
} as const;

const readinessLabels: Record<Language, Record<ReadinessStatus, string>> = {
  zh: { ready: "可发布", needs_review: "待评估", needs_package: "待打包", needs_manual_edit: "建议人工修改", quality_low: "质量偏低", missing_content: "缺少内容", unknown: "未知" },
  en: { ready: "Ready", needs_review: "Needs review", needs_package: "Needs package", needs_manual_edit: "Needs manual edit", quality_low: "Quality low", missing_content: "Missing content", unknown: "Unknown" },
};

const variantLabels: Record<Language, Record<"manual" | "publish" | "package" | "source", string>> = {
  zh: { manual: "使用人工修改版", publish: "使用发布稿", package: "使用发布包", source: "使用原文" },
  en: { manual: "Use manual edit", publish: "Use publish draft", package: "Use publishing package", source: "Use source" },
};

const zhActionLabels: Record<string, string> = {
  "Generate or restore article content": "生成或恢复文章内容",
  "Generate a publishing package": "生成发布包",
  "Review the quality report": "查看质量报告",
  "Create a manual edit": "完成人工修改",
  "Run content quality evaluation": "执行内容质量评估",
  "Review warnings and edit the article": "检查 warning 并人工修改",
  "Review content metadata": "检查内容元数据",
};

function actionLabel(language: Language, action: string) {
  return language === "zh" ? zhActionLabels[action] || action : action;
}

type YesNo = "all" | "yes" | "no";

export function PublishingDeskPage({ language, onOpenLibrary }: { language: Language; onOpenLibrary: (contentId: string, variant: ContentVariant) => void }) {
  const text = copy[language];
  const content = useContentIndexData();
  const [desk, setDesk] = useState<PublishingDesk | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<ContentType | "all">("all");
  const [status, setStatus] = useState<ReadinessStatus | "all">("all");
  const [manual, setManual] = useState<YesNo>("all");
  const [packaged, setPackaged] = useState<YesNo>("all");
  const [ready, setReady] = useState<YesNo>("all");
  const [detailMode, setDetailMode] = useState<EditorMode>("preview");

  const load = async (rebuild = false) => {
    setLoading(true); setError("");
    try {
      const next = rebuild ? await rebuildPublishingDesk() : await fetchPublishingDesk();
      setDesk(next);
      if (rebuild) await content.refreshContentIndex();
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const items = desk?.items || [];
  const visible = useMemo(() => items.filter((item) => {
    const matchesQuery = item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
    return matchesQuery && (type === "all" || item.content_type === type) && (status === "all" || item.readiness_status === status)
      && (manual === "all" || item.has_manual_edit === (manual === "yes"))
      && (packaged === "all" || Boolean(item.package_path) === (packaged === "yes"))
      && (ready === "all" || item.readiness_status === "ready" === (ready === "yes"));
  }), [items, manual, packaged, query, ready, status, type]);

  const open = (item: ContentItem, variant = getBestPublishVariant(item), mode: EditorMode = "preview") => {
    setDetailMode(mode); void content.openMarkdown(item.content_id, variant).catch(() => undefined);
  };
  const show = (value: string) => { setMessage(value); window.setTimeout(() => setMessage(""), 4500); };
  const handleExport = async (item: ContentItem) => {
    setBusy(true); setError("");
    try {
      const result = await exportContentMarkdown(item);
      downloadMarkdown(`${item.safe_name || item.content_id}_${result.variant}.md`, result.content);
      show(`${text.exportDone}: ${text.used} = ${variantLabels[language][result.variant]}; ${text.hasSource} = ${result.source_urls.length}; package = ${result.has_package ? text.yes : text.no}; ${text.warning} = ${result.warnings.length}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const handleManualPackage = async (item: ContentItem) => {
    setBusy(true); setError("");
    try { await packageFromManual(item.content_id); await load(true); show(text.partial); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const handlePackageMissing = async () => {
    setBusy(true); setError("");
    try {
      const result = await packageMissingPublishingContent(); setDesk(result.desk); await content.refreshContentIndex();
      show(`${text.partial}: ${result.packaged_count}/${result.attempted_count}${result.warnings.length ? `; ${result.warnings.length} ${text.warning}` : ""}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const readyItems = items.filter((item) => item.readiness_status === "ready");
  const readyIndexMarkdown = () => [
    "# Publishing Ready Content", "", `Generated at: ${desk?.generated_at || new Date().toISOString()}`, "",
    ...readyItems.flatMap((item) => [`## ${item.title}`, "", `- Content ID: \`${item.content_id}\``, `- Best variant: ${getBestPublishVariant(item)}`, `- Quality: ${item.quality_score ?? "-"}`, `- Package: ${item.package_path || "-"}`, ...(item.source_urls.length ? item.source_urls.map((url) => `- Source: ${url}`) : []), ""]),
  ].join("\n");
  const summary = desk?.summary;

  return <div className="page-stack publishing-desk-page">
    <section className="panel page-panel">
      <div className="panel-header page-header"><div><h2>{text.title}</h2><p>{text.subtitle}</p></div><span className="publishing-generated">{formatDate(desk?.generated_at || "")}</span></div>
      <div className="workspace-metrics publishing-metrics">
        <div><FileCheck2 size={18} /><span>{text.ready}</span><strong>{summary?.ready_count ?? 0}</strong></div>
        <div><FileQuestion size={18} /><span>{text.review}</span><strong>{summary?.needs_review_count ?? 0}</strong></div>
        <div><PackageCheck size={18} /><span>{text.package}</span><strong>{summary?.needs_package_count ?? 0}</strong></div>
        <div><Gauge size={18} /><span>{text.low}</span><strong>{summary?.quality_low_count ?? 0}</strong></div>
        <div><UserRoundCheck size={18} /><span>{text.manual}</span><strong>{summary?.manual_edit_count ?? 0}</strong></div>
        <div><FileText size={18} /><span>{text.total}</span><strong>{items.length}</strong></div>
      </div>
    </section>
    <section className="panel page-panel publishing-actions">
      <button className="secondary-button icon-command" type="button" disabled={busy || loading} onClick={() => void load(true)}><RefreshCw size={15} />{text.rebuild}</button>
      <button className="secondary-button icon-command" type="button" disabled={busy || loading} onClick={() => void handlePackageMissing()}><PackageCheck size={15} />{text.packageMissing}</button>
      <button className="secondary-button icon-command" type="button" disabled={!readyItems.length} onClick={() => void copyText(readyItems.map((item) => `${item.title} (${item.content_id})`).join("\n")).then(() => show(text.copied))}><Clipboard size={15} />{text.copyReady}</button>
      <button className="secondary-button icon-command" type="button" disabled={!readyItems.length} onClick={() => downloadMarkdown("publishing_ready_index.md", readyIndexMarkdown())}><Download size={15} />{text.exportIndex}</button>
    </section>
    <section className="panel page-panel">
      <div className="content-filter-grid publishing-filters">
        <label className="content-search"><span>{text.search}</span><div><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} /></div></label>
        <label><span>{text.type}</span><select value={type} onChange={(event) => setType(event.target.value as typeof type)}><option value="all">{text.all}</option>{publishingTypes.map((value) => <option key={value} value={value}>{contentTypeLabels[language][value]}</option>)}</select></label>
        <label><span>{text.status}</span><select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="all">{text.all}</option>{statusOrder.map((value) => <option key={value} value={value}>{readinessLabels[language][value]}</option>)}</select></label>
        {([[text.manualFilter, manual, setManual], [text.packageFilter, packaged, setPackaged], [text.readyFilter, ready, setReady]] as const).map(([label, value, setter]) => <label key={label}><span>{label}</span><select value={value} onChange={(event) => setter(event.target.value as YesNo)}><option value="all">{text.all}</option><option value="yes">{text.yes}</option><option value="no">{text.no}</option></select></label>)}
      </div>
      {error ? <div className="banner error">{error}</div> : null}{message ? <div className="banner success">{message}</div> : null}{loading ? <p className="empty-state">{text.loading}</p> : null}
      {!loading && visible.length ? <div className="table-wrap"><table className="ranking-table data-table publishing-table"><thead><tr>{text.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{visible.map((item) => <tr key={item.content_id}>
        <td><button className="content-title-button" type="button" onClick={() => open(item)}><strong>{item.title}</strong></button><small>{item.content_id}</small></td>
        <td><span className={`content-kind content-kind-${item.content_type}`}>{contentTypeLabels[language][item.content_type]}</span></td>
        <td><span className={`readiness-badge readiness-${item.readiness_status}`}>{readinessLabels[language][item.readiness_status]}</span></td>
        <td>{item.quality_score == null ? "-" : item.quality_score.toFixed(1)}</td><td>{item.has_manual_edit ? <Check size={16} className="positive-icon" /> : "-"}</td><td>{item.package_path ? <Check size={16} className="positive-icon" /> : "-"}</td>
        <td>{item.agent_run_id || "-"}</td><td>{formatDate(item.manual_edit_updated_at || item.updated_at || item.created_at || item.date)}</td><td className="publishing-next-action">{item.next_actions[0] ? actionLabel(language, item.next_actions[0]) : "-"}{item.next_actions.length > 1 ? <small>+{item.next_actions.length - 1}</small> : null}</td>
        <td><div className="content-row-actions"><button type="button" onClick={() => open(item)}><Sparkles size={13} />{text.detail}</button><button type="button" onClick={() => open(item, item.publish_path ? "publish" : "source", "edit")}><Pencil size={13} />{text.edit}</button>{item.publish_path ? <button type="button" onClick={() => open(item, "publish")}><FileText size={13} />{text.publishDraft}</button> : null}{item.package_path ? <button type="button" onClick={() => open(item, "package")}><PackageCheck size={13} />{text.viewPackage}</button> : null}<button type="button" disabled={busy} onClick={() => void handleExport(item)}><Download size={13} />{text.export}</button>{item.has_manual_edit ? <button type="button" disabled={busy} onClick={() => void handleManualPackage(item)}><PackageCheck size={13} />{text.packageManual}</button> : null}<button type="button" onClick={() => onOpenLibrary(item.content_id, getBestPublishVariant(item))}><ExternalLink size={13} />{text.library}</button></div></td>
      </tr>)}</tbody></table></div> : null}
      {!loading && !visible.length ? <p className="empty-state">{text.noData}</p> : null}
    </section>
    <ContentPreviewPanel item={content.selectedItem} variant={content.selectedVariant} markdownContent={content.markdownContent} markdownPath={content.markdownPath} language={language} loading={content.markdownLoading} error={content.markdownError} initialMode={detailMode} onClose={content.closeMarkdown} onOpenLibrary={onOpenLibrary} />
  </div>;
}
