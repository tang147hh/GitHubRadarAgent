import type { Language } from "./i18n";
import type { ContentItem, ContentType, ContentVariant } from "./types";

export const contentTypeLabels: Record<Language, Record<ContentType, string>> = {
  zh: {
    github_article: "GitHub 项目文章",
    github_custom_article: "指定项目文章",
    ai_news_article: "AI 新闻文章",
    ai_news_digest: "AI 日报",
    agent_artifact: "Agent 产物",
    manual_edit: "人工修改版",
  },
  en: {
    github_article: "GitHub Article",
    github_custom_article: "Custom GitHub Article",
    ai_news_article: "AI News Article",
    ai_news_digest: "AI Digest",
    agent_artifact: "Agent Artifact",
    manual_edit: "Manual Edit",
  },
};

export const contentStatusLabels: Record<Language, Record<string, string>> = {
  zh: { draft: "草稿", reviewed: "已评审", publish_ready: "可发布", packaged: "已打包", unknown: "未知" },
  en: { draft: "Draft", reviewed: "Reviewed", publish_ready: "Publish ready", packaged: "Packaged", unknown: "Unknown" },
};

export const contentVariantLabels: Record<Language, Record<ContentVariant, string>> = {
  zh: { source: "原文", publish: "发布稿", package: "发布包", report: "报告", manual: "人工修改版" },
  en: { source: "Source", publish: "Publish draft", package: "Package", report: "Report", manual: "Manual edit" },
};

export const contentVariants: Array<{ key: ContentVariant; path: keyof ContentItem }> = [
  { key: "source", path: "markdown_path" },
  { key: "publish", path: "publish_path" },
  { key: "package", path: "package_path" },
  { key: "report", path: "report_path" },
  { key: "manual", path: "manual_edit_path" },
];

export function contentStatusLabel(language: Language, status: string) {
  return contentStatusLabels[language][status] || status || contentStatusLabels[language].unknown;
}
