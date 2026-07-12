import { Archive, ArrowRight, Check, GitCompare, PackageCheck, Pencil, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { contentStatusLabel, contentTypeLabels, contentVariants, contentVariantLabels } from "../contentDisplay";
import { useContentIndexData } from "../hooks/useContentIndexData";
import type { Language } from "../i18n";
import type { ContentItem, ContentType, ContentVariant } from "../types";
import { ContentPreviewPanel } from "./ContentPreviewPanel";
import type { EditorMode } from "./ContentDetailPanel";

type Mode = "github" | "news" | "digest";
type Props = {
  language: Language;
  title: string;
  types: ContentType[];
  mode: Mode;
  packageOnly?: boolean;
  onOpenLibrary: (contentId: string, variant: ContentVariant) => void;
};

export function ContentWorkspaceList({ language, title, types, mode, packageOnly = false, onOpenLibrary }: Props) {
  const data = useContentIndexData();
  const [detailMode, setDetailMode] = useState<EditorMode>("preview");
  const labels = language === "zh"
    ? { empty: "Content Index 中暂无符合条件的内容。", reload: "刷新", repository: "项目", type: "类型", quality: "质量分", status: "状态", ready: "可发布", sources: "来源数", newsIds: "News IDs", date: "日期", package: "发布包", run: "Agent Run", actions: "操作", library: "在内容库打开", edit: "编辑", compare: "对比", edited: "已人工修改" }
    : { empty: "No matching content exists in the Content Index.", reload: "Refresh", repository: "Repository", type: "Type", quality: "Quality", status: "Status", ready: "Publish ready", sources: "Sources", newsIds: "News IDs", date: "Date", package: "Package", run: "Agent Run", actions: "Actions", library: "Open in Content Library", edit: "Edit", compare: "Compare", edited: "Manually edited" };
  const items = useMemo(() => data.items.filter((item) => types.includes(item.content_type) && (!packageOnly || Boolean(item.package_path))), [data.items, packageOnly, types]);

  const open = (item: ContentItem, variant: ContentVariant, nextMode: EditorMode = "preview") => { setDetailMode(nextMode); void data.openMarkdown(item.content_id, variant).catch(() => undefined); };
  const columns = mode === "github"
    ? [labels.repository, labels.type, labels.quality, labels.status, labels.package, labels.run, labels.actions]
    : mode === "news"
      ? [labels.quality, labels.ready, labels.sources, labels.newsIds, labels.run, labels.actions]
      : [labels.date, labels.status, labels.sources, labels.quality, labels.package, labels.actions];

  return <div className="page-stack content-workspace-page">
    <section className="panel page-panel">
      <div className="panel-header"><div><h2>{title}</h2><p>Content Index</p></div><button className="secondary-button icon-command" type="button" disabled={data.loading} onClick={() => void data.reload()}><RefreshCw size={16} className={data.loading ? "spin-icon" : ""} />{labels.reload}</button></div>
      {data.error ? <div className="banner error">{data.error}</div> : null}
      {data.loading ? <p className="empty-state">...</p> : null}
      {!data.loading && items.length ? <div className="table-wrap"><table className="ranking-table data-table workspace-content-table"><thead><tr><th>{language === "zh" ? "标题" : "Title"}</th>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>
        {items.map((item) => <tr key={item.content_id}>
          <td><strong>{item.title}</strong>{item.has_manual_edit ? <small className="manual-edit-marker">{labels.edited}</small> : null}</td>
          {mode === "github" ? <><td>{item.repo_full_name || "-"}</td><td><span className={`content-kind content-kind-${item.content_type}`}>{contentTypeLabels[language][item.content_type]}</span></td><td>{item.quality_score == null ? "-" : item.quality_score.toFixed(1)}</td><td>{contentStatusLabel(language, item.status)}</td><td>{item.package_path ? <PackageCheck size={16} className="positive-icon" /> : "-"}</td><td>{item.agent_run_id || "-"}</td></> : null}
          {mode === "news" ? <><td>{item.quality_score == null ? "-" : item.quality_score.toFixed(1)}</td><td>{item.publish_ready ? <Check size={16} className="positive-icon" /> : "-"}</td><td>{item.source_urls.length}</td><td className="compact-list-cell">{item.news_ids.join(", ") || "-"}</td><td>{item.agent_run_id || "-"}</td></> : null}
          {mode === "digest" ? <><td>{item.date || "-"}</td><td>{contentStatusLabel(language, item.status)}</td><td>{item.source_urls.length}</td><td>{item.quality_score == null ? "-" : item.quality_score.toFixed(1)}</td><td>{item.package_path ? <PackageCheck size={16} className="positive-icon" /> : "-"}</td></> : null}
          <td><div className="content-row-actions">{contentVariants.map((variant) => item[variant.path] ? <button key={variant.key} type="button" onClick={() => open(item, variant.key)}>{contentVariantLabels[language][variant.key]}</button> : null)}<button type="button" onClick={() => open(item, item.publish_path ? "publish" : "source", "edit")}><Pencil size={13} />{labels.edit}</button><button type="button" onClick={() => open(item, "source", "compare")}><GitCompare size={13} />{labels.compare}</button><button type="button" onClick={() => onOpenLibrary(item.content_id, "source")}><ArrowRight size={13} />{labels.library}</button></div></td>
        </tr>)}
      </tbody></table></div> : null}
      {!data.loading && !items.length ? <div className="library-empty"><Archive size={28} /><p>{labels.empty}</p></div> : null}
    </section>
    <ContentPreviewPanel item={data.selectedItem} variant={data.selectedVariant} markdownContent={data.markdownContent} markdownPath={data.markdownPath} language={language} loading={data.markdownLoading} error={data.markdownError} initialMode={detailMode} onClose={data.closeMarkdown} onOpenLibrary={onOpenLibrary} />
  </div>;
}
