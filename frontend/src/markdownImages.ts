import { API_BASE_URL } from "./api";

const DATE_PATTERN = /outputs\/(\d{4}-\d{2}-\d{2})\//;

export function markdownImageSrc(src: string | undefined, sourcePath: string, fallbackDate?: string) {
  if (!src) return "";
  if (/^(https?:|data:|blob:|#)/i.test(src)) return src;
  const normalized = src.replace(/^\.?\//, "");
  if (!normalized.startsWith("assets/")) return src;
  const date = DATE_PATTERN.exec(sourcePath)?.[1] || fallbackDate;
  if (!date) return src;
  return `${API_BASE_URL}/api/outputs/${encodeURIComponent(date)}/${normalized
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}
