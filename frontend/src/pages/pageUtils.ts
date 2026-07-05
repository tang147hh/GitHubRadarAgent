import type { ReviewItem } from "../types";
export { copyText, downloadMarkdown, extractTitleFromMarkdown, safeFilename } from "../fileUtils";

export const asArray = <T>(value: T[] | undefined | null): T[] => (Array.isArray(value) ? value : []);

export function formatNumber(value: number | string | undefined | null) {
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "string" && value.trim()) return value;
  return "-";
}

export function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function projectName(item: { full_name?: string; project?: string; name?: string }) {
  return item.full_name || item.project || item.name || "-";
}

export function projectUrl(item: { html_url?: string; url?: string; full_name?: string; project?: string }) {
  return item.html_url || item.url || (item.full_name || item.project ? `https://github.com/${item.full_name || item.project}` : "");
}

export function scorePercent(value: number | undefined, max: number) {
  return `${Math.max(0, Math.min(100, ((value || 0) / max) * 100))}%`;
}

export function reviewMaxScore(key: keyof ReviewItem) {
  if (key === "factual_score") return 30;
  if (key === "title_score" || key === "structure_score") return 20;
  return 15;
}
