import { Check, Clipboard, Play, RefreshCw, RotateCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveAgentRun,
  fetchAgentRun,
  fetchLatestAgentRun,
  resumeAgentRun,
  startAgentRun,
} from "../api";
import type { Language } from "../i18n";
import type { AgentRun } from "../types";
import { useContentIndexData } from "../hooks/useContentIndexData";

const copyPath = (path: string) => navigator.clipboard?.writeText(path);

const labels = {
  zh: {
    goal: "输入目标",
    goalPlaceholder: "帮我写 https://github.com/sharkdp/bat 的公众号文章，从程序员日常体验写",
    autoApprove: "自动批准工具执行",
    maxRecovery: "最大恢复次数",
    start: "启动 Agent",
    starting: "正在执行",
    currentRun: "当前运行",
    runId: "运行 ID",
    skill: "使用 Skill",
    status: "状态",
    recoveries: "恢复次数",
    reflection: "反思",
    enabled: "启用",
    disabled: "关闭",
    plan: "执行计划",
    tool: "工具",
    reason: "原因",
    observation: "观察结果",
    artifacts: "产物",
    reflections: "反思记录",
    decision: "决定",
    issues: "问题",
    recoveryActions: "修正动作",
    approval: "等待确认",
    approvalNotes: "审批备注（可选）",
    approve: "批准继续",
    reject: "拒绝",
    resume: "继续执行",
    refresh: "刷新",
    noRun: "还没有 Agent 运行记录。",
    noSteps: "当前计划没有步骤。",
    noReflections: "尚无反思记录。",
    noArtifacts: "尚无产物。",
    copy: "复制路径",
    error: "错误",
    loadFailed: "读取 Agent 运行失败",
    startFailed: "启动 Agent 失败",
    approvalFailed: "审批失败",
    resumeFailed: "继续执行失败",
  },
  en: {
    goal: "Goal",
    goalPlaceholder: "Write a WeChat article about https://github.com/sharkdp/bat from a developer's daily experience",
    autoApprove: "Auto-approve tool execution",
    maxRecovery: "Max recovery count",
    start: "Start Agent",
    starting: "Running",
    currentRun: "Current Run",
    runId: "Run ID",
    skill: "Skill",
    status: "Status",
    recoveries: "Recoveries",
    reflection: "Reflection",
    enabled: "Enabled",
    disabled: "Disabled",
    plan: "Execution Plan",
    tool: "Tool",
    reason: "Reason",
    observation: "Observation",
    artifacts: "Artifacts",
    reflections: "Reflections",
    decision: "Decision",
    issues: "Issues",
    recoveryActions: "Recovery actions",
    approval: "Approval Required",
    approvalNotes: "Approval notes (optional)",
    approve: "Approve and continue",
    reject: "Reject",
    resume: "Resume",
    refresh: "Refresh",
    noRun: "No Agent run exists yet.",
    noSteps: "This plan has no steps.",
    noReflections: "No reflections yet.",
    noArtifacts: "No artifacts yet.",
    copy: "Copy path",
    error: "Error",
    loadFailed: "Failed to load Agent run",
    startFailed: "Failed to start Agent",
    approvalFailed: "Approval failed",
    resumeFailed: "Resume failed",
  },
} as const;

const zhStatusLabels: Record<string, string> = {
  planned: "已计划",
  pending: "待执行",
  running: "执行中",
  needs_input: "等待输入",
  waiting_approval: "等待批准",
  approved: "已批准",
  rejected: "已拒绝",
  succeeded: "已成功",
  failed: "已失败",
  skipped: "已跳过",
  pass: "通过",
  needs_recovery: "需要修正",
  unrecoverable: "无法恢复",
};

const zhActionLabels: Record<string, string> = {
  insert_step: "插入步骤",
  update_step_args: "更新步骤参数",
  skip_step: "跳过步骤",
  stop_run: "停止运行",
};

function displayStatus(status: string, language: Language) {
  return language === "zh" ? zhStatusLabels[status] || status : status;
}

function displayAction(action: string, language: Language) {
  return language === "zh" ? zhActionLabels[action] || action : action;
}

function localizeAgentText(value: string | null | undefined, language: Language) {
  const original = String(value || "");
  if (language !== "zh" || !original) return original;
  const exact: Record<string, string> = {
    "Goal includes a GitHub repository URL, so write one custom project article.": "目标中包含 GitHub 仓库地址，因此生成一篇指定项目文章。",
    "Waiting for user approval before tool execution.": "正在等待用户批准执行该工具。",
    "Tool execution approved; ready to resume.": "工具执行已获批准，可以继续运行。",
    "Tool execution rejected by user.": "用户已拒绝执行该工具。",
    "Result passed deterministic reflection checks.": "结果已通过确定性反思检查。",
  };
  if (exact[original]) return exact[original];
  return original
    .replace(/^About to run ([^.]+)\. Reason: /, "即将执行工具 $1。执行原因：")
    .replace(/\. Expected effects\/artifacts: /, "。预计产生的影响或产物：")
    .replace(/Goal includes a GitHub repository URL, so write one custom project article\./g, "目标中包含 GitHub 仓库地址，因此生成一篇指定项目文章。")
    .replace(/Waiting for user approval before tool execution\./g, "正在等待用户批准执行该工具。")
    .replace(/reads\/writes /g, "读取并写入 ")
    .replace(/may write /g, "可能写入 ")
    .replace(/writes /g, "写入 ")
    .replace(/^([\w.]+) succeeded: /, "$1 执行成功：")
    .replace(/^([\w.]+) failed: /, "$1 执行失败：")
    .replace(/Wrote custom GitHub article for ([^.]+)\./, "已为 $1 生成指定 GitHub 项目文章。")
    .replace(/github\.write_custom_article failed\./g, "github.write_custom_article 执行失败。")
    .replace(/GitHub owner\/repo format is invalid/gi, "GitHub owner/repo 格式不合法")
    .replace(/。。/g, "。")
    .replace(/; /g, "；");
}

export function AgentConsolePage({ language }: { language: Language }) {
  const contentIndex = useContentIndexData();
  const text = labels[language];
  const [goal, setGoal] = useState("");
  const [autoApprove, setAutoApprove] = useState(false);
  const [maxRecoveryCount, setMaxRecoveryCount] = useState(3);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");

  const updateRun = useCallback((next: AgentRun, syncOnSuccess = false) => {
    setRun(next);
    setError("");
    if (syncOnSuccess && next.status === "succeeded") {
      void contentIndex.handleContentMutationSuccess({ artifact_paths: next.artifacts }, {
        artifactPaths: next.artifacts, agentRunId: next.run_id, preferredVariant: "source", openAfterSync: false,
      }).catch(() => undefined);
    }
  }, [contentIndex.handleContentMutationSuccess]);

  const refresh = useCallback(async () => {
    try {
      const next = run?.run_id ? await fetchAgentRun(run.run_id) : await fetchLatestAgentRun();
      updateRun(next);
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status !== 404) setError(err instanceof Error ? err.message : text.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [run?.run_id, updateRun]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!run || !["running", "planned"].includes(run.status)) return;
    const timer = window.setInterval(() => void fetchAgentRun(run.run_id).then((next) => updateRun(next, true)).catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [run, updateRun]);

  const handleStart = async () => {
    if (!goal.trim()) return;
    setActing(true);
    setError("");
    try {
      updateRun(await startAgentRun({ goal: goal.trim(), auto_approve: autoApprove, max_recovery_count: maxRecoveryCount }), true);
    } catch (err) {
      setError(err instanceof Error ? err.message : text.startFailed);
    } finally {
      setActing(false);
    }
  };

  const handleApproval = async (approved: boolean) => {
    if (!run) return;
    setActing(true);
    setError("");
    try {
      const decided = await approveAgentRun(run.run_id, { approved, notes: notes.trim() || undefined });
      setNotes("");
      updateRun(approved ? await resumeAgentRun(decided.run_id) : decided, approved);
    } catch (err) {
      setError(err instanceof Error ? err.message : text.approvalFailed);
    } finally {
      setActing(false);
    }
  };

  const handleResume = async () => {
    if (!run) return;
    setActing(true);
    try {
      updateRun(await resumeAgentRun(run.run_id), true);
    } catch (err) {
      setError(err instanceof Error ? err.message : text.resumeFailed);
    } finally {
      setActing(false);
    }
  };

  const canResume = useMemo(
    () => ["planned", "running"].includes(run?.status || "") && run?.plan.steps.some((step) => step.status === "approved"),
    [run],
  );

  return (
    <div className="agent-console-page">
      <section className="panel agent-goal-panel">
        <label className="agent-goal-field">
          <span>{text.goal}</span>
          <textarea value={goal} onChange={(event) => setGoal(event.target.value)} placeholder={text.goalPlaceholder} />
        </label>
        <div className="agent-run-controls">
          <label className="agent-toggle">
            <input type="checkbox" checked={autoApprove} onChange={(event) => setAutoApprove(event.target.checked)} />
            <span>{text.autoApprove}</span>
          </label>
          <label className="agent-number-field">
            <span>{text.maxRecovery}</span>
            <input type="number" min={0} max={20} value={maxRecoveryCount} onChange={(event) => setMaxRecoveryCount(Number(event.target.value))} />
          </label>
          <button className="primary-button" type="button" disabled={acting || !goal.trim()} onClick={() => void handleStart()}>
            <Play size={16} /> {acting ? text.starting : text.start}
          </button>
          <button className="secondary-button icon-command" type="button" disabled={loading || acting} onClick={() => void refresh()} title={text.refresh}>
            <RefreshCw size={16} /> {text.refresh}
          </button>
        </div>
      </section>

      {error ? <div className="banner error">{error}</div> : null}
      {loading ? <p className="empty-state">...</p> : null}
      {!loading && !run ? <p className="empty-state">{text.noRun}</p> : null}

      {run ? (
        <>
          <section className="panel agent-summary-panel">
            <div className="panel-header"><h2>{text.currentRun}</h2></div>
            <div className="agent-summary-grid">
              <div><span>{text.runId}</span><strong>{run.run_id}</strong></div>
              <div><span>{text.skill}</span><strong>{run.skill_name || "-"}</strong></div>
              <div><span>{text.status}</span><strong className={`agent-status agent-status-${run.status}`}>{displayStatus(run.status, language)}</strong></div>
              <div><span>{text.recoveries}</span><strong>{run.recovery_count} / {run.max_recovery_count}</strong></div>
              <div><span>{text.reflection}</span><strong>{run.reflection_enabled ? text.enabled : text.disabled}</strong></div>
            </div>
            {canResume ? <button className="secondary-button" type="button" onClick={() => void handleResume()}><RotateCw size={16} /> {text.resume}</button> : null}
          </section>

          {run.status === "needs_input" && run.pending_approval_step_id ? (
            <section className="panel agent-approval-panel">
              <div className="panel-header"><h2>{text.approval}</h2><span className="agent-status agent-status-waiting_approval">{run.pending_approval_step_id}</span></div>
              <p>{localizeAgentText(run.approval_prompt, language)}</p>
              <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder={text.approvalNotes} />
              <div className="agent-approval-actions">
                <button className="primary-button" type="button" disabled={acting} onClick={() => void handleApproval(true)}><Check size={16} /> {text.approve}</button>
                <button className="danger-button" type="button" disabled={acting} onClick={() => void handleApproval(false)}><X size={16} /> {text.reject}</button>
              </div>
            </section>
          ) : null}

          <section className="panel agent-plan-panel">
            <div className="panel-header"><h2>{text.plan}</h2><span>{run.plan.steps.length}</span></div>
            <div className="agent-step-list">
              {run.plan.steps.map((step) => (
                <article className={`agent-step agent-step-${step.status}`} key={step.step_id}>
                  <div className="agent-step-heading">
                    <div><span>{step.step_id}</span><strong>{step.tool_name}</strong></div>
                    <span className={`agent-status agent-status-${step.status}`}>{displayStatus(step.status, language)}</span>
                  </div>
                  <dl>
                    <div><dt>{text.reason}</dt><dd>{localizeAgentText(step.reason, language) || "-"}</dd></div>
                    <div><dt>{text.observation}</dt><dd>{localizeAgentText(step.observation, language) || "-"}</dd></div>
                    {step.error ? <div><dt>{text.error}</dt><dd className="agent-error-text">{localizeAgentText(step.error, language)}</dd></div> : null}
                    {step.artifacts.length ? <div><dt>{text.artifacts}</dt><dd>{step.artifacts.map((item) => <code key={item}>{item}</code>)}</dd></div> : null}
                  </dl>
                </article>
              ))}
              {!run.plan.steps.length ? <p className="empty-state">{text.noSteps}</p> : null}
            </div>
          </section>

          <div className="agent-lower-grid">
            <section className="panel">
              <div className="panel-header"><h2>{text.reflections}</h2><span>{run.reflections.length}</span></div>
              <div className="agent-log-list">
                {run.reflections.map((reflection) => (
                  <article key={reflection.reflection_id}>
                    <div><strong>{reflection.tool_name}</strong><span className={`agent-status agent-status-${reflection.status}`}>{displayStatus(reflection.status, language)}</span></div>
                    <p><b>{text.decision}:</b> {localizeAgentText(reflection.decision, language)}</p>
                    {reflection.issues.length ? <p><b>{text.issues}:</b> {reflection.issues.map((issue) => localizeAgentText(issue, language)).join("；")}</p> : null}
                    {reflection.recovery_actions.map((action) => <p key={action.action_id}><b>{text.recoveryActions}:</b> {displayAction(action.action_type, language)} {action.tool_name || ""} - {localizeAgentText(action.reason, language)}</p>)}
                  </article>
                ))}
                {!run.reflections.length ? <p className="empty-state">{text.noReflections}</p> : null}
              </div>
            </section>
            <section className="panel">
              <div className="panel-header"><h2>{text.artifacts}</h2><span>{run.artifacts.length}</span></div>
              <div className="agent-artifact-list">
                {run.artifacts.map((artifact) => (
                  <div key={artifact}><code>{artifact}</code><button type="button" title={text.copy} onClick={() => void copyPath(artifact)}><Clipboard size={15} /></button></div>
                ))}
                {!run.artifacts.length ? <p className="empty-state">{text.noArtifacts}</p> : null}
              </div>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
