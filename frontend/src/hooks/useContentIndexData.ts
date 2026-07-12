import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject, ReactNode } from "react";
import { fetchContentIndex, fetchContentMarkdown, rebuildContentIndex as rebuildContentIndexApi } from "../api";
import type { ContentIndex, ContentItem, ContentSource, ContentType, ContentVariant } from "../types";

export type ContentSyncOptions = {
  artifactPaths?: string[];
  contentTypes?: ContentType[];
  preferredVariant?: ContentVariant;
  agentRunId?: string;
  repoFullName?: string;
  newsArticleId?: string;
  digest?: boolean;
  openAfterSync?: boolean;
};

export type ContentSyncResult = {
  index: ContentIndex | null;
  item: ContentItem | null;
  opened: boolean;
  warning?: string;
};

export type ContentSyncStatus = "idle" | "syncing" | "updated" | "opened" | "not_found" | "failed";

type MutationResult = Record<string, unknown> | null | undefined;
type ContentNavigator = (contentId: string, variant: ContentVariant) => void;

type ContentIndexContextValue = ReturnType<typeof useContentIndexValue>;
const ContentIndexContext = createContext<ContentIndexContextValue | null>(null);

const variantPaths: Record<ContentVariant, keyof ContentItem> = {
  source: "markdown_path",
  publish: "publish_path",
  package: "package_path",
  report: "report_path",
  manual: "manual_edit_path",
};

function normalizedPath(path: string) {
  return path.replace(/\\/g, "/").replace(/^\.\//, "").replace(/\/+$/, "");
}

function pathsMatch(left?: string | null, right?: string | null) {
  if (!left || !right) return false;
  const a = normalizedPath(left);
  const b = normalizedPath(right);
  return a === b || a.endsWith(`/${b}`) || b.endsWith(`/${a}`);
}

function updatedTime(item: ContentItem) {
  const value = item.updated_at || item.created_at || item.date;
  const parsed = Date.parse(value || "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

function chooseLatest(items: ContentItem[], preferredVariant?: ContentVariant) {
  const withVariant = preferredVariant ? items.filter((item) => Boolean(item[variantPaths[preferredVariant]])) : [];
  return [...(withVariant.length ? withVariant : items)].sort((a, b) => updatedTime(b) - updatedTime(a))[0] || null;
}

export function findContentAfterMutation(items: ContentItem[], options: ContentSyncOptions) {
  const artifactPaths = (options.artifactPaths || []).filter(Boolean);
  const pathKeys: Array<keyof ContentItem> = ["markdown_path", "publish_path", "package_path", "report_path", "manual_edit_path"];
  const pathMatches = artifactPaths.length
    ? items.filter((item) => pathKeys.some((key) => artifactPaths.some((path) => pathsMatch(item[key] as string | null, path))))
    : [];
  if (pathMatches.length) return chooseLatest(pathMatches, options.preferredVariant);

  if (options.agentRunId) {
    const matches = items.filter((item) => item.agent_run_id === options.agentRunId);
    if (matches.length) return chooseLatest(matches, options.preferredVariant);
  }
  if (options.repoFullName) {
    const wanted = options.repoFullName.toLowerCase();
    const matches = items.filter((item) => item.repo_full_name?.toLowerCase() === wanted);
    if (matches.length) return chooseLatest(matches, options.preferredVariant);
  }
  if (options.newsArticleId) {
    const matches = items.filter((item) => item.source_id === options.newsArticleId || item.news_ids.includes(options.newsArticleId!));
    if (matches.length) return chooseLatest(matches, options.preferredVariant);
  }
  const fallbackTypes = options.digest ? ["ai_news_digest" as ContentType] : options.contentTypes || [];
  const matches = fallbackTypes.length ? items.filter((item) => fallbackTypes.includes(item.content_type)) : [];
  return chooseLatest(matches, options.preferredVariant);
}

function collectMutationHints(result: MutationResult) {
  const artifactPaths = new Set<string>();
  let contentHint: Record<string, unknown> = {};
  const pathKeys = new Set(["output_markdown_path", "markdown_path", "publish_path", "package_path", "packaged_article_path", "report_path", "path"]);
  const visit = (value: unknown, depth = 0) => {
    if (!value || depth > 3) return;
    if (Array.isArray(value)) {
      value.forEach((entry) => visit(entry, depth + 1));
      return;
    }
    if (typeof value !== "object") return;
    const record = value as Record<string, unknown>;
    if (record.content_hint && typeof record.content_hint === "object") contentHint = record.content_hint as Record<string, unknown>;
    if (Array.isArray(record.artifact_paths)) record.artifact_paths.forEach((path) => typeof path === "string" && artifactPaths.add(path));
    Object.entries(record).forEach(([key, entry]) => {
      if (pathKeys.has(key) && typeof entry === "string" && entry.endsWith(".md")) artifactPaths.add(entry);
      else if (key === "packages" || key === "final_article" || key === "result") visit(entry, depth + 1);
    });
  };
  visit(result);
  return { artifactPaths: [...artifactPaths], contentHint };
}

function useContentIndexValue(navigateRef: MutableRefObject<ContentNavigator | null>) {
  const [index, setIndex] = useState<ContentIndex | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<ContentSyncStatus>("idle");
  const [syncWarning, setSyncWarning] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<ContentItem | null>(null);
  const [selectedVariant, setSelectedVariant] = useState<ContentVariant | null>(null);
  const [markdownContent, setMarkdownContent] = useState("");
  const [markdownPath, setMarkdownPath] = useState("");
  const [markdownLoading, setMarkdownLoading] = useState(false);
  const [markdownError, setMarkdownError] = useState<string | null>(null);

  const refreshContentIndex = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchContentIndex();
      setIndex(next);
      return next;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Content index is unavailable";
      setError(message);
      throw reason;
    } finally {
      setLoading(false);
    }
  }, []);

  const rebuildContentIndex = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await rebuildContentIndexApi();
      const next = await fetchContentIndex();
      setIndex(next);
      return next;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Content index rebuild failed";
      setError(message);
      throw reason;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refreshContentIndex().catch(() => undefined); }, [refreshContentIndex]);

  const syncContentAfterMutation = useCallback(async (options: ContentSyncOptions = {}): Promise<ContentSyncResult> => {
    setSyncStatus("syncing");
    setSyncWarning(null);
    try {
      const next = await rebuildContentIndex();
      const item = findContentAfterMutation(next.items || [], options);
      if (!item) {
        const warning = "Content was generated but the new index item could not be located.";
        setSyncStatus("not_found");
        setSyncWarning(warning);
        return { index: next, item: null, opened: false, warning };
      }
      if (options.openAfterSync && navigateRef.current) {
        const requestedVariant = options.preferredVariant || "source";
        const variant = item[variantPaths[requestedVariant]]
          ? requestedVariant
          : (["source", "publish", "package", "report", "manual"] as ContentVariant[]).find((candidate) => Boolean(item[variantPaths[candidate]])) || "source";
        navigateRef.current(item.content_id, variant);
        setSyncStatus("opened");
        return { index: next, item, opened: true };
      }
      setSyncStatus("updated");
      return { index: next, item, opened: false };
    } catch (reason) {
      setSyncStatus("failed");
      const warning = reason instanceof Error ? reason.message : "Content index update failed";
      setSyncWarning(warning);
      return { index: null, item: null, opened: false, warning };
    }
  }, [navigateRef, rebuildContentIndex]);

  const handleContentMutationSuccess = useCallback(async (result: MutationResult, options: ContentSyncOptions = {}) => {
    const hints = collectMutationHints(result);
    const contentHint = hints.contentHint;
    return syncContentAfterMutation({
      ...options,
      artifactPaths: [...hints.artifactPaths, ...(options.artifactPaths || [])],
      contentTypes: options.contentTypes || (typeof contentHint.content_type === "string" ? [contentHint.content_type as ContentType] : undefined),
      preferredVariant: options.preferredVariant || (contentHint.preferred_variant as ContentVariant | undefined),
      agentRunId: options.agentRunId || (contentHint.agent_run_id as string | undefined),
      repoFullName: options.repoFullName || (contentHint.repo_full_name as string | undefined),
      newsArticleId: options.newsArticleId || (contentHint.news_article_id as string | undefined),
    });
  }, [syncContentAfterMutation]);

  const items = useMemo(() => index?.items || [], [index]);
  useEffect(() => {
    if (!selectedItem) return;
    const refreshed = items.find((item) => item.content_id === selectedItem.content_id);
    if (refreshed && refreshed !== selectedItem) setSelectedItem(refreshed);
  }, [items, selectedItem]);
  const filterByType = useCallback((types: ContentType[]) => items.filter((item) => types.includes(item.content_type)), [items]);
  const filterBySource = useCallback((source: ContentSource) => items.filter((item) => item.source === source), [items]);
  const findByAgentRunId = useCallback((agentRunId: string) => items.filter((item) => item.agent_run_id === agentRunId), [items]);
  const findByRepoFullName = useCallback((repoFullName: string) => items.filter((item) => item.repo_full_name === repoFullName), [items]);
  const findByNewsIds = useCallback((newsIds: string[]) => { const wanted = new Set(newsIds); return items.filter((item) => item.news_ids.some((id) => wanted.has(id))); }, [items]);

  const openMarkdown = useCallback(async (contentId: string, variant: ContentVariant = "source") => {
    setSelectedItem(items.find((candidate) => candidate.content_id === contentId) || null);
    setSelectedVariant(variant); setMarkdownContent(""); setMarkdownPath(""); setMarkdownLoading(true); setMarkdownError(null);
    try {
      const result = await fetchContentMarkdown(contentId, variant);
      setMarkdownContent(result.content); setMarkdownPath(result.path); return result;
    } catch (reason) {
      setMarkdownError(reason instanceof Error ? reason.message : "Markdown is unavailable"); throw reason;
    } finally { setMarkdownLoading(false); }
  }, [items]);
  const closeMarkdown = useCallback(() => { setSelectedItem(null); setSelectedVariant(null); setMarkdownContent(""); setMarkdownPath(""); setMarkdownError(null); }, []);
  const setContentNavigator = useCallback((navigator: ContentNavigator | null) => { navigateRef.current = navigator; }, [navigateRef]);

  return {
    index, items, loading, error, syncStatus, syncWarning,
    reload: refreshContentIndex, rebuild: rebuildContentIndex, refreshContentIndex, rebuildContentIndex, syncContentAfterMutation,
    handleContentMutationSuccess, setContentNavigator, filterByType, filterBySource, findByAgentRunId, findByRepoFullName,
    findByNewsIds, openContentItem: openMarkdown, selectedItem, selectedVariant, markdownContent, markdownPath,
    markdownLoading, markdownError, openMarkdown, closeMarkdown,
  };
}

export function ContentIndexProvider({ children }: { children: ReactNode }) {
  const navigateRef = useRef<ContentNavigator | null>(null);
  const value = useContentIndexValue(navigateRef);
  return createElement(ContentIndexContext.Provider, { value }, children);
}

export function useContentIndexData() {
  const value = useContext(ContentIndexContext);
  if (!value) throw new Error("useContentIndexData must be used inside ContentIndexProvider");
  return value;
}
