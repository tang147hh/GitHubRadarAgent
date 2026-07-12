import { ArrowRight, Check, Clipboard, GitCompare, PackageCheck, Pencil, Play, RefreshCw, RotateCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { ContentPreviewPanel } from "../components/ContentPreviewPanel";
import type { EditorMode } from "../components/ContentDetailPanel";
import { contentStatusLabel, contentTypeLabels, contentVariants, contentVariantLabels } from "../contentDisplay";
import { useAgentRunData } from "../hooks/useAgentRunData";
import { useContentIndexData } from "../hooks/useContentIndexData";
import type { Language } from "../i18n";
import type { ContentItem, ContentVariant, PageKey } from "../types";
import { formatDate } from "./pageUtils";

const copy = {
  zh: { noRun: "还没有 Agent 运行记录。", noData: "当前没有数据。", currentRun: "最新运行", goal: "目标", status: "状态", skill: "Skill", created: "创建时间", recoveries: "恢复次数", refresh: "刷新", quickGoal: "输入新目标", recentArtifacts: "最近 Agent 产物摘要", plan: "执行步骤", tool: "工具", reason: "原因", result: "执行结果", arguments: "参数", reflections: "反思记录", decision: "决定", issues: "问题", actions: "修正动作", approval: "等待人工确认", notes: "确认备注（可选）", approve: "批准并继续", reject: "拒绝", resume: "继续执行", artifacts: "原始产物", linked: "已关联内容", unrecognized: "未识别产物", publishable: "可发布", needsPackage: "待打包", qualityLow: "质量偏低", packaged: "已打包内容", publishingDesk: "查看发布工作台", copyPath: "复制路径", openLibrary: "在内容库打开", history: "运行记录", goalPlaceholder: "输入希望 Agent 完成的具体目标", autoApprove: "自动批准工具执行", maxRecovery: "最大恢复次数", start: "启动 Agent", running: "执行中" },
  en: { noRun: "No Agent run exists yet.", noData: "No data available.", currentRun: "Latest run", goal: "Goal", status: "Status", skill: "Skill", created: "Created", recoveries: "Recoveries", refresh: "Refresh", quickGoal: "Start a new goal", recentArtifacts: "Recent Agent artifact summary", plan: "Execution steps", tool: "Tool", reason: "Reason", result: "Result", arguments: "Arguments", reflections: "Reflections", decision: "Decision", issues: "Issues", actions: "Recovery actions", approval: "Approval required", notes: "Approval notes (optional)", approve: "Approve and continue", reject: "Reject", resume: "Resume", artifacts: "Raw artifacts", linked: "Linked content", unrecognized: "Unrecognized artifacts", publishable: "Ready", needsPackage: "Needs package", qualityLow: "Quality low", packaged: "Packaged content", publishingDesk: "View Publishing Desk", copyPath: "Copy path", openLibrary: "Open in Content Library", history: "Run activity", goalPlaceholder: "Describe the concrete outcome for the Agent", autoApprove: "Auto-approve tool execution", maxRecovery: "Max recovery count", start: "Start Agent", running: "Running" },
} as const;

function normalizeArtifactPath(path: string) {
  return path.replace(/\\/g, "/").replace(/^.*?\/(outputs|workspace)\//, "$1/").replace(/^\.\//, "");
}

function itemPaths(item: ContentItem) {
  return [item.markdown_path, item.publish_path, item.package_path, item.report_path].filter((path): path is string => Boolean(path)).map(normalizeArtifactPath);
}

function artifactMatchesItem(artifact: string, item: ContentItem) {
  const normalized = normalizeArtifactPath(artifact);
  return itemPaths(item).some((path) => normalized === path || normalized.endsWith(`/${path}`) || path.endsWith(`/${normalized}`));
}

function State({ language }: { language: Language }) {
  const { run, loading, error } = useAgentRunData();
  const text = copy[language];
  if (loading) return <p className="empty-state">...</p>;
  if (error) return <div className="banner error">{error}</div>;
  if (!run) return <p className="empty-state">{text.noRun}</p>;
  return null;
}

function RunSummary({ language }: { language: Language }) {
  const { run, refresh, loading } = useAgentRunData();
  const text = copy[language];
  if (!run) return <State language={language} />;
  return <section className="panel page-panel agent-summary-panel"><div className="panel-header"><h2>{text.currentRun}</h2><button className="secondary-button icon-command" type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={16} />{text.refresh}</button></div>
    <div className="agent-summary-grid"><div><span>Run ID</span><strong>{run.run_id}</strong></div><div><span>{text.status}</span><strong className={`agent-status agent-status-${run.status}`}>{run.status}</strong></div><div><span>{text.skill}</span><strong>{run.skill_name || "-"}</strong></div><div><span>{text.recoveries}</span><strong>{run.recovery_count} / {run.max_recovery_count}</strong></div></div>
  </section>;
}

export function AgentWorkbenchPage({ language, onNavigate }: { language: Language; onNavigate: (page: PageKey) => void }) {
  const { run } = useAgentRunData(); const content = useContentIndexData(); const text = copy[language];
  const linked = useMemo(() => run ? content.items.filter((item) => item.agent_run_id === run.run_id || run.artifacts.some((artifact) => artifactMatchesItem(artifact, item))) : [], [content.items, run]);
  return <div className="page-stack"><RunSummary language={language} />
    <section className="panel page-panel workspace-actions"><div className="panel-header"><h2>{text.quickGoal}</h2></div><div><button className="workspace-link" type="button" onClick={() => onNavigate("agent-goal")}><span>{text.quickGoal}</span><ArrowRight size={16} /></button><button className="workspace-link" type="button" onClick={() => onNavigate("agent-approvals")}><span>{text.approval}</span><ArrowRight size={16} /></button><button className="workspace-link" type="button" onClick={() => onNavigate("publishing-desk")}><span>{text.publishingDesk}</span><ArrowRight size={16} /></button></div></section>
    <section className="panel page-panel"><div className="panel-header"><h2>{text.recentArtifacts}</h2></div><div className="workspace-metrics agent-content-metrics"><div><Check size={18} /><span>{text.publishable}</span><strong>{linked.filter((item) => item.readiness_status === "ready").length}</strong></div><div><PackageCheck size={18} /><span>{text.needsPackage}</span><strong>{linked.filter((item) => item.readiness_status === "needs_package").length}</strong></div><div><RefreshCw size={18} /><span>{text.qualityLow}</span><strong>{linked.filter((item) => item.readiness_status === "quality_low").length}</strong></div></div>{!content.loading && !linked.length ? <p className="empty-state">{text.noData}</p> : null}</section>
  </div>;
}

export function AgentGoalPage({ language }: { language: Language }) {
  const { start, acting } = useAgentRunData(); const text = copy[language];
  const [goal, setGoal] = useState(""); const [autoApprove, setAutoApprove] = useState(false); const [maxRecovery, setMaxRecovery] = useState(3);
  return <section className="panel page-panel agent-goal-panel"><label className="agent-goal-field"><span>{text.goal}</span><textarea value={goal} onChange={(event) => setGoal(event.target.value)} placeholder={text.goalPlaceholder} /></label>
    <div className="agent-run-controls"><label className="agent-toggle"><input type="checkbox" checked={autoApprove} onChange={(event) => setAutoApprove(event.target.checked)} /><span>{text.autoApprove}</span></label><label className="agent-number-field"><span>{text.maxRecovery}</span><input type="number" min={0} max={20} value={maxRecovery} onChange={(event) => setMaxRecovery(Number(event.target.value))} /></label><button className="primary-button" type="button" disabled={acting || !goal.trim()} onClick={() => void start({ goal: goal.trim(), autoApprove, maxRecoveryCount: maxRecovery })}><Play size={16} />{acting ? text.running : text.start}</button></div>
  </section>;
}

export function AgentPlanPage({ language }: { language: Language }) {
  const { run } = useAgentRunData(); const text = copy[language];
  if (!run) return <State language={language} />;
  return <section className="panel page-panel"><div className="panel-header"><h2>{text.plan}</h2><span>{run.plan.steps.length}</span></div><div className="agent-step-list">{run.plan.steps.map((step) => <article className={`agent-step agent-step-${step.status}`} key={step.step_id}><div className="agent-step-heading"><div><span>{step.step_id}</span><strong>{step.tool_name}</strong></div><span className={`agent-status agent-status-${step.status}`}>{step.status}</span></div><p>{step.reason || "-"}</p></article>)}{!run.plan.steps.length ? <p className="empty-state">{text.noData}</p> : null}</div></section>;
}

export function AgentToolsPage({ language }: { language: Language }) {
  const { run } = useAgentRunData(); const text = copy[language];
  if (!run) return <State language={language} />;
  return <section className="panel page-panel"><div className="panel-header"><h2>{text.tool}</h2><span>{run.plan.steps.length}</span></div><div className="agent-tool-list">{run.plan.steps.map((step) => <article key={step.step_id}><div className="agent-step-heading"><strong>{step.tool_name}</strong><span className={`agent-status agent-status-${step.status}`}>{step.status}</span></div><dl><div><dt>{text.reason}</dt><dd>{step.reason || "-"}</dd></div><div><dt>{text.arguments}</dt><dd><code>{JSON.stringify(step.arguments)}</code></dd></div><div><dt>{text.result}</dt><dd>{step.observation || step.error || "-"}</dd></div></dl></article>)}</div></section>;
}

export function AgentReflectionsPage({ language }: { language: Language }) {
  const { run } = useAgentRunData(); const text = copy[language];
  if (!run) return <State language={language} />;
  return <section className="panel page-panel"><div className="panel-header"><h2>{text.reflections}</h2><span>{run.reflections.length}</span></div><div className="agent-log-list">{run.reflections.map((item) => <article key={item.reflection_id}><div><strong>{item.tool_name}</strong><span className={`agent-status agent-status-${item.status}`}>{item.status}</span></div><p><b>{text.decision}:</b> {item.decision}</p><p><b>{text.issues}:</b> {item.issues.join("; ") || "-"}</p><p><b>{text.actions}:</b> {item.recovery_actions.map((action) => action.reason).join("; ") || "-"}</p></article>)}{!run.reflections.length ? <p className="empty-state">{text.noData}</p> : null}</div></section>;
}

export function AgentApprovalsPage({ language }: { language: Language }) {
  const { run, acting, decide, resume } = useAgentRunData(); const text = copy[language]; const [notes, setNotes] = useState("");
  if (!run) return <State language={language} />;
  const pending = run.status === "needs_input" && run.pending_approval_step_id;
  return <section className="panel page-panel agent-approval-panel"><div className="panel-header"><h2>{text.approval}</h2>{pending ? <span className="agent-status agent-status-waiting_approval">{run.pending_approval_step_id}</span> : null}</div>{pending ? <><p>{run.approval_prompt}</p><textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder={text.notes} /><div className="agent-approval-actions"><button className="primary-button" type="button" disabled={acting} onClick={() => void decide(true, notes)}><Check size={16} />{text.approve}</button><button className="danger-button" type="button" disabled={acting} onClick={() => void decide(false, notes)}><X size={16} />{text.reject}</button></div></> : <><p className="empty-state">{text.noData}</p>{run.plan.steps.some((step) => step.status === "approved") ? <button className="secondary-button" type="button" onClick={() => void resume()}><RotateCw size={16} />{text.resume}</button> : null}</>}</section>;
}

export function AgentArtifactsPage({ language, onNavigate, onOpenLibrary }: { language: Language; onNavigate: (page: PageKey) => void; onOpenLibrary: (contentId: string, variant: ContentVariant) => void }) {
  const { run } = useAgentRunData(); const content = useContentIndexData(); const text = copy[language];
  const [detailMode, setDetailMode] = useState<EditorMode>("preview");
  if (!run) return <State language={language} />;
  const linked = content.items.filter((item) => item.agent_run_id === run.run_id || run.artifacts.some((artifact) => artifactMatchesItem(artifact, item)));
  const unrecognized = run.artifacts.filter((artifact) => !linked.some((item) => artifactMatchesItem(artifact, item)));
  const open = (item: ContentItem, variant: ContentVariant, mode: EditorMode = "preview") => { setDetailMode(mode); void content.openMarkdown(item.content_id, variant).catch(() => undefined); };
  return <div className="page-stack agent-artifacts-page">
    <section className="panel page-panel"><div className="panel-header"><div><h2>{text.artifacts}</h2><p>Agent Run ID: {run.run_id}</p></div><button className="secondary-button" type="button" onClick={() => onNavigate("content-library")}>{text.openLibrary}<ArrowRight size={16} /></button></div><div className="agent-artifact-list">{run.artifacts.map((artifact) => <div key={artifact}><code>{artifact}</code><div className="agent-artifact-actions"><button type="button" title={text.copyPath} onClick={() => void navigator.clipboard?.writeText(artifact)}><Clipboard size={15} /></button></div></div>)}{!run.artifacts.length ? <p className="empty-state">{text.noData}</p> : null}</div></section>
    <section className="panel page-panel"><div className="panel-header"><h2>{text.linked}</h2><span>{linked.length}</span></div>{content.error ? <div className="banner error">{content.error}</div> : null}{content.loading ? <p className="empty-state">...</p> : null}<div className="linked-content-list">{linked.map((item) => <article key={item.content_id}><div><div><strong>{item.title}</strong><span className={`content-kind content-kind-${item.content_type}`}>{contentTypeLabels[language][item.content_type]}</span></div><span>{contentStatusLabel(language, item.status)} · {item.quality_score == null ? "-" : item.quality_score.toFixed(1)} {item.package_path ? `· ${text.packaged}` : ""}</span></div><div className="content-row-actions">{contentVariants.map((variant) => item[variant.path] ? <button key={variant.key} type="button" onClick={() => open(item, variant.key)}>{contentVariantLabels[language][variant.key]}</button> : null)}<button type="button" onClick={() => open(item, item.publish_path ? "publish" : "source", "edit")}><Pencil size={13} />{language === "zh" ? "编辑" : "Edit"}</button><button type="button" onClick={() => open(item, "source", "compare")}><GitCompare size={13} />{language === "zh" ? "对比" : "Compare"}</button><button type="button" onClick={() => onOpenLibrary(item.content_id, "source")}><ArrowRight size={13} />{text.openLibrary}</button></div></article>)}{!content.loading && !linked.length ? <p className="empty-state">{text.noData}</p> : null}</div></section>
    <section className="panel page-panel"><div className="panel-header"><h2>{text.unrecognized}</h2><span>{unrecognized.length}</span></div><div className="agent-artifact-list">{unrecognized.map((artifact) => <div key={artifact}><code>{artifact}</code></div>)}{!unrecognized.length ? <p className="empty-state">{text.noData}</p> : null}</div></section>
    <ContentPreviewPanel item={content.selectedItem} variant={content.selectedVariant} markdownContent={content.markdownContent} markdownPath={content.markdownPath} language={language} loading={content.markdownLoading} error={content.markdownError} initialMode={detailMode} onClose={content.closeMarkdown} onOpenLibrary={onOpenLibrary} />
  </div>;
}

export function AgentRunsPage({ language }: { language: Language }) {
  const { run } = useAgentRunData(); const text = copy[language];
  if (!run) return <State language={language} />;
  return <div className="page-stack"><RunSummary language={language} /><section className="panel page-panel"><div className="panel-header"><h2>{text.history}</h2></div><div className="agent-run-timeline"><div><strong>{run.status}</strong><span>{formatDate(run.finished_at || run.started_at || run.created_at)}</span><p>{run.goal}</p></div>{run.approval_history.map((item) => <div key={`${item.step_id}:${item.decided_at}`}><strong>{item.approved ? text.approve : text.reject}</strong><span>{formatDate(item.decided_at)}</span><p>{item.tool_name} · {item.notes || "-"}</p></div>)}</div></section></div>;
}
