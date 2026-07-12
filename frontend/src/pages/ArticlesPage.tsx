import { Copy, Download, ExternalLink, FileText, PackagePlus, PanelLeftClose, PanelLeftOpen, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchFinalArticle, fetchFinalArticles, fetchPackagedArticle, fetchReport, packageArticles } from "../api";
import { copyText, downloadMarkdown } from "../fileUtils";
import type { Language, Translation } from "../i18n";
import { markdownImageSrc } from "../markdownImages";
import { useContentIndexData } from "../hooks/useContentIndexData";
import type { FinalArticleItem } from "../types";
import { projectName, projectUrl } from "./pageUtils";

type ArticlesPageProps = {
  t: Translation;
  language: Language;
};

function articleTitle(article: FinalArticleItem, language: Language) {
  if (article.title) return article.title;
  const project = article.full_name || article.project || article.safe_name || "";
  return language === "zh" ? `${project} 终稿文章` : `${project} final article`;
}

function fileNameForArticle(article: FinalArticleItem) {
  return `${article.safe_name || (article.full_name || article.project || "final_article").replace("/", "__")}.md`;
}

function articleMeta(article: FinalArticleItem, t: Translation) {
  return [
    `${projectName(article)} · ${article.word_count ?? article.words ?? "-"} ${t.labels.words}`,
    article.generation_mode ? `${t.labels.generationMode}: ${article.generation_mode}` : "",
    article.narrative_pattern ? `${t.labels.narrativePattern}: ${article.narrative_pattern}` : "",
    `${t.labels.contentPlanUsed}: ${article.content_plan_used ? "yes" : "no"}`,
    `${t.labels.humanized}: ${article.humanized ? "yes" : "no"}`,
    article.quality_score != null ? `${t.labels.qualityScore}: ${article.quality_score}` : "",
    article.quality_score != null
      ? `${t.labels.articleQuality}: ${article.quality_publish_ready ? t.labels.publishable : t.labels.needsRevision}`
      : "",
    article.ai_smell_score != null ? `${t.labels.naturalness}: ${article.ai_smell_score}` : "",
    article.template_risk != null ? `${t.labels.templateRisk}: ${article.template_risk}` : "",
    article.localization_score != null ? `${t.labels.localizationScore}: ${article.localization_score}` : "",
  ].filter(Boolean).join(" · ");
}

function articleKey(article: FinalArticleItem) {
  return [article.source || "daily", article.safe_name || projectName(article), article.markdown_path || article.local_markdown_path || ""].join(":");
}

function sourceLabel(article: FinalArticleItem, language: Language) {
  if (article.source === "custom") return language === "zh" ? "手动指定" : "Manual";
  return language === "zh" ? "系统发现" : "Discovered";
}

export function ArticlesPage({ t, language }: ArticlesPageProps) {
  const contentIndex = useContentIndexData();
  const [articles, setArticles] = useState<FinalArticleItem[]>([]);
  const [selectedArticleKey, setSelectedArticleKey] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [message, setMessage] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [loadingArticle, setLoadingArticle] = useState(false);
  const [packagingSafeName, setPackagingSafeName] = useState("");
  const [bulkPackaging, setBulkPackaging] = useState(false);
  const [error, setError] = useState("");
  const [isArticleListCollapsed, setIsArticleListCollapsed] = useState(false);

  const selectedArticle = useMemo(
    () => articles.find((article) => articleKey(article) === selectedArticleKey) || articles[0],
    [articles, selectedArticleKey],
  );

  const loadArticle = useCallback((article: FinalArticleItem | undefined) => {
    if (!article?.safe_name) return;
    setLoadingArticle(true);
    fetchFinalArticle(article.safe_name, article.source)
      .then((payload) => {
        setMarkdown(payload.content_markdown || "");
        setSourcePath(payload.path || "");
        setSelectedArticleKey(articleKey(article));
        setError("");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : t.messages.previewFailed);
      })
      .finally(() => setLoadingArticle(false));
  }, [t.messages.previewFailed]);

  const loadArticles = useCallback(async (options?: { selectFirst?: boolean }) => {
    setLoadingList(true);
    try {
      const payload = await fetchFinalArticles();
      const nextArticles = payload.articles || [];
      setArticles(nextArticles);
      setError("");
      if (options?.selectFirst && nextArticles[0]) loadArticle(nextArticles[0]);
      return nextArticles;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load final articles");
      return [];
    } finally {
      setLoadingList(false);
    }
  }, [loadArticle]);

  useEffect(() => {
    let cancelled = false;
    void loadArticles({ selectFirst: true }).then(() => {
      if (cancelled) return;
    });
    return () => {
      cancelled = true;
    };
  }, [loadArticles]);

  const flash = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage((current) => (current === text ? "" : current)), 2500);
  };

  const handleCopy = async () => {
    const copied = markdown ? await copyText(markdown) : false;
    flash(copied ? t.messages.copySuccess : t.messages.copyFailed);
  };

  const handleDownload = () => {
    if (!selectedArticle || !markdown) {
      flash(t.messages.downloadFailed);
      return;
    }
    downloadMarkdown(fileNameForArticle(selectedArticle), markdown);
  };

  const handleDraftIndex = async () => {
    setLoadingArticle(true);
    try {
      const report = await fetchReport("articles_index");
      setSelectedArticleKey("");
      setSourcePath(report.path || "");
      setMarkdown(report.content_markdown || "");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t.messages.reportFailed);
    } finally {
      setLoadingArticle(false);
    }
  };

  const handleViewPackage = async () => {
    if (!selectedArticle?.safe_name) return;
    setLoadingArticle(true);
    try {
      const payload = await fetchPackagedArticle(selectedArticle.safe_name, selectedArticle.source);
      setSourcePath(payload.path || selectedArticle.packaged_article_path || "");
      setMarkdown(payload.content_markdown || "");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t.messages.previewFailed);
    } finally {
      setLoadingArticle(false);
    }
  };

  const handleGeneratePackage = async (article = selectedArticle) => {
    if (!article?.safe_name) return;
    setPackagingSafeName(article.safe_name);
    try {
      const packaged = await packageArticles({
        safe_names: [article.safe_name],
        full_names: article.full_name ? [article.full_name] : [],
      });
      const refreshed = await loadArticles();
      const nextArticle =
        refreshed.find((item) => articleKey(item) === articleKey(article)) ||
        refreshed.find((item) => item.safe_name === article.safe_name) ||
        article;
      flash(t.messages.packageSuccess || "发布包已生成");
      setSelectedArticleKey(articleKey(nextArticle));
      const payload = await fetchPackagedArticle(article.safe_name, article.source);
      setSourcePath(payload.path || nextArticle.packaged_article_path || "");
      setMarkdown(payload.content_markdown || "");
      setError("");
      await contentIndex.handleContentMutationSuccess(packaged as unknown as Record<string, unknown>, {
        contentTypes: [article.source === "custom" ? "github_custom_article" : "github_article"],
        repoFullName: article.full_name, preferredVariant: "package", openAfterSync: true,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t.messages.previewFailed);
    } finally {
      setPackagingSafeName("");
    }
  };

  const handleGeneratePackages = async () => {
    setBulkPackaging(true);
    try {
      const packaged = await packageArticles({ top: articles.filter((article) => article.source !== "custom").length || undefined });
      await loadArticles();
      await contentIndex.handleContentMutationSuccess(packaged as unknown as Record<string, unknown>, {
        contentTypes: ["github_article"], preferredVariant: "package", openAfterSync: false,
      });
      flash(t.messages.packageSuccess || "发布包已生成");
    } catch (err) {
      setError(err instanceof Error ? err.message : t.messages.previewFailed);
    } finally {
      setBulkPackaging(false);
    }
  };

  const handleDownloadPackage = async () => {
    if (!selectedArticle?.safe_name) {
      flash(t.messages.downloadFailed);
      return;
    }
    try {
      const payload = await fetchPackagedArticle(selectedArticle.safe_name, selectedArticle.source);
      const content = payload.content_markdown || "";
      if (!content) {
        flash(t.messages.downloadFailed);
        return;
      }
      downloadMarkdown(`${selectedArticle.safe_name}_packaged.md`, content);
    } catch {
      flash(t.messages.downloadFailed);
    }
  };

  return (
    <div className={`articles-layout ${isArticleListCollapsed ? "list-collapsed" : ""}`}>
      <section className="panel list-panel article-list-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.actions.articleList}</h2>
            <p>{t.pageSubtitles.articles}</p>
          </div>
          <button
            className="icon-text-button"
            type="button"
            onClick={() => void handleGeneratePackages()}
            disabled={bulkPackaging || loadingList || articles.length === 0}
          >
            {bulkPackaging ? <RefreshCw size={16} aria-hidden="true" /> : <PackagePlus size={16} aria-hidden="true" />}
            <span>{bulkPackaging ? t.actions.generatingPackage : t.actions.generatePackages}</span>
          </button>
        </div>

        {loadingList ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}
        {!loadingList && articles.length === 0 ? <p className="empty-state">{t.empty.noFinalArticles}</p> : null}

        <div className="side-list">
          {articles.map((article) => (
            <button
              className={`side-list-item ${articleKey(article) === selectedArticleKey ? "active" : ""}`}
              type="button"
              key={articleKey(article)}
              onClick={() => loadArticle(article)}
            >
              <strong>
                {articleTitle(article, language)}
                <span className={`soft-badge source-badge ${article.source === "custom" ? "running" : "pending"}`}>
                  {sourceLabel(article, language)}
                </span>
                {article.quality_score != null ? (
                  <span className={`soft-badge source-badge ${article.quality_publish_ready ? "" : "failed"}`}>
                    {t.labels.qualityScore}: {article.quality_score}
                  </span>
                ) : null}
              </strong>
              <span>{articleMeta(article, t)}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel detail-panel article-preview-panel article-preview-page">
        <div className="panel-header page-header">
          <div>
            <h2>{selectedArticle && selectedArticleKey ? articleTitle(selectedArticle, language) : t.actions.viewDraftIndex}</h2>
            <p>{sourcePath || t.empty.noPreviewTitle}</p>
            {selectedArticle && selectedArticleKey ? (
              <p>
                {sourceLabel(selectedArticle, language)} ·{" "}
                {selectedArticle.generation_mode ? `${t.labels.generationMode}: ${selectedArticle.generation_mode} · ` : ""}
                {selectedArticle.narrative_pattern ? `${t.labels.narrativePattern}: ${selectedArticle.narrative_pattern} · ` : ""}
                {t.labels.contentPlanUsed}: {selectedArticle.content_plan_used ? "yes" : "no"} ·{" "}
                {t.labels.humanized}: {selectedArticle.humanized ? "yes" : "no"}
                {selectedArticle.quality_score != null
                  ? ` · ${t.labels.qualityScore}: ${selectedArticle.quality_score} · ${
                    selectedArticle.quality_publish_ready ? t.labels.publishable : t.labels.needsRevision
                  }`
                  : ""}
                {selectedArticle.ai_smell_score != null ? ` · ${t.labels.naturalness}: ${selectedArticle.ai_smell_score}` : ""}
                {selectedArticle.template_risk != null ? ` · ${t.labels.templateRisk}: ${selectedArticle.template_risk}` : ""}
                {selectedArticle.localization_score != null ? ` · ${t.labels.localizationScore}: ${selectedArticle.localization_score}` : ""}
              </p>
            ) : null}
          </div>
          <div className="row-actions wrap-actions">
            <button
              className="icon-text-button"
              type="button"
              onClick={() => setIsArticleListCollapsed((current) => !current)}
              title={isArticleListCollapsed ? t.actions.showList : t.actions.hideList}
              aria-label={isArticleListCollapsed ? t.actions.showList : t.actions.hideList}
            >
              {isArticleListCollapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
              <span>{isArticleListCollapsed ? t.actions.showList : t.actions.hideList}</span>
            </button>
            <button className="icon-text-button" type="button" onClick={handleCopy} disabled={!markdown}>
              <Copy size={16} aria-hidden="true" />
              <span>{t.actions.copyMarkdown}</span>
            </button>
            <button className="icon-text-button" type="button" onClick={handleDownload} disabled={!markdown || !selectedArticle || !selectedArticleKey}>
              <Download size={16} aria-hidden="true" />
              <span>{t.actions.downloadMarkdown}</span>
            </button>
            {selectedArticle?.safe_name ? (
              <button
                className="icon-text-button"
                type="button"
                onClick={() => void handleGeneratePackage()}
                disabled={Boolean(packagingSafeName)}
              >
                {packagingSafeName === selectedArticle.safe_name ? <RefreshCw size={16} aria-hidden="true" /> : <PackagePlus size={16} aria-hidden="true" />}
                <span>
                  {packagingSafeName === selectedArticle.safe_name
                    ? t.actions.generatingPackage
                    : selectedArticle.packaged_article_available || selectedArticle.packaged_article_path || selectedArticle.package_path
                      ? t.actions.regeneratePackage
                      : t.actions.generatePackage}
                </span>
              </button>
            ) : null}
            {selectedArticle?.packaged_article_available || selectedArticle?.packaged_article_path || selectedArticle?.package_path ? (
              <>
                <button className="icon-text-button" type="button" onClick={handleViewPackage}>
                  <FileText size={16} aria-hidden="true" />
                  <span>{t.actions.viewPackage}</span>
                </button>
                <button className="icon-text-button" type="button" onClick={() => void handleDownloadPackage()}>
                  <Download size={16} aria-hidden="true" />
                  <span>{t.actions.downloadPackage}</span>
                </button>
              </>
            ) : null}
            {selectedArticle && selectedArticleKey && projectUrl(selectedArticle) ? (
              <a className="icon-text-button" href={projectUrl(selectedArticle)} target="_blank" rel="noreferrer">
                <ExternalLink size={16} aria-hidden="true" />
                <span>{t.actions.openGithub}</span>
              </a>
            ) : null}
            <button className="icon-text-button" type="button" onClick={handleDraftIndex}>
              <FileText size={16} aria-hidden="true" />
              <span>{t.actions.viewDraftIndex}</span>
            </button>
          </div>
        </div>

        {message ? <div className="banner warning">{message}</div> : null}
        {loadingArticle ? <p className="empty-state">{t.actions.loading}</p> : null}
        <article className="markdown-preview markdown-body full-markdown">
          {markdown ? (
            <ReactMarkdown
              components={{
                img: ({ src, alt, ...props }) => (
                  <img {...props} alt={alt || ""} src={markdownImageSrc(src, sourcePath)} />
                ),
              }}
            >
              {markdown}
            </ReactMarkdown>
          ) : (
            <p className="empty-state">{t.empty.noPreviewTitle}</p>
          )}
        </article>
      </section>
    </div>
  );
}
