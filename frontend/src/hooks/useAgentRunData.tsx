import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { approveAgentRun, fetchAgentRun, fetchLatestAgentRun, resumeAgentRun, startAgentRun } from "../api";
import type { AgentRun } from "../types";
import { useContentIndexData } from "./useContentIndexData";

type StartOptions = { goal: string; autoApprove: boolean; maxRecoveryCount: number };

type AgentRunContextValue = {
  run: AgentRun | null;
  loading: boolean;
  acting: boolean;
  error: string;
  refresh: () => Promise<void>;
  start: (options: StartOptions) => Promise<void>;
  decide: (approved: boolean, notes?: string) => Promise<void>;
  resume: () => Promise<void>;
};

const AgentRunContext = createContext<AgentRunContextValue | null>(null);

export function AgentRunProvider({ children }: { children: ReactNode }) {
  const contentIndex = useContentIndexData();
  const syncedRunIds = useRef(new Set<string>());
  const [run, setRun] = useState<AgentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");

  const syncSucceededRun = useCallback((next: AgentRun) => {
    if (next.status !== "succeeded" || syncedRunIds.current.has(next.run_id)) return;
    syncedRunIds.current.add(next.run_id);
    void contentIndex.handleContentMutationSuccess({ artifact_paths: next.artifacts }, {
      artifactPaths: next.artifacts,
      agentRunId: next.run_id,
      preferredVariant: next.artifacts.some((path) => path.includes("package") || path.includes("packaged")) ? "package" : "source",
      openAfterSync: false,
    }).catch(() => undefined);
  }, [contentIndex.handleContentMutationSuccess]);

  const updateRun = useCallback((next: AgentRun, syncOnSuccess = false) => {
    setRun(next);
    setError("");
    if (syncOnSuccess) syncSucceededRun(next);
  }, [syncSucceededRun]);

  const refresh = useCallback(async () => {
    try {
      updateRun(run?.run_id ? await fetchAgentRun(run.run_id) : await fetchLatestAgentRun());
    } catch (err) {
      if ((err as { status?: number }).status !== 404) setError(err instanceof Error ? err.message : "Failed to load Agent run");
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

  const start = useCallback(async ({ goal, autoApprove, maxRecoveryCount }: StartOptions) => {
    setActing(true);
    setError("");
    try {
      updateRun(await startAgentRun({ goal, auto_approve: autoApprove, max_recovery_count: maxRecoveryCount }), true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start Agent");
    } finally {
      setActing(false);
    }
  }, [updateRun]);

  const decide = useCallback(async (approved: boolean, notes?: string) => {
    if (!run) return;
    setActing(true);
    setError("");
    try {
      const decided = await approveAgentRun(run.run_id, { approved, notes: notes?.trim() || undefined });
      updateRun(approved ? await resumeAgentRun(decided.run_id) : decided, approved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setActing(false);
    }
  }, [run, updateRun]);

  const resume = useCallback(async () => {
    if (!run) return;
    setActing(true);
    try {
      updateRun(await resumeAgentRun(run.run_id), true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resume failed");
    } finally {
      setActing(false);
    }
  }, [run, updateRun]);

  const value = useMemo(() => ({ run, loading, acting, error, refresh, start, decide, resume }), [run, loading, acting, error, refresh, start, decide, resume]);
  return <AgentRunContext.Provider value={value}>{children}</AgentRunContext.Provider>;
}

export function useAgentRunData() {
  const value = useContext(AgentRunContext);
  if (!value) throw new Error("useAgentRunData must be used inside AgentRunProvider");
  return value;
}
