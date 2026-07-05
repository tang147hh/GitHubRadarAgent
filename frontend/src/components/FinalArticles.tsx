import { Download, Eye } from "lucide-react";
import type { Language, Translation } from "../i18n";
import type { FinalArticleItem } from "../types";

type FinalArticlesProps = {
  t: Translation;
  language: Language;
  articles: FinalArticleItem[];
  onPreview: (article: FinalArticleItem) => void;
  onDownload: (article: FinalArticleItem) => void;
  loadingArticle?: string | null;
};

const articleTitle = (article: FinalArticleItem, language: Language) => {
  if (article.title) return article.title;
  const project = article.full_name || article.project || "";
  return language === "zh" ? `${project} 终稿文章` : `${project} final article`;
};

export function FinalArticles({ t, language, articles, onPreview, onDownload, loadingArticle }: FinalArticlesProps) {
  return (
    <section className="panel final-articles-panel">
      <div className="panel-header">
        <h2>{t.sections.finalArticles}</h2>
      </div>

      <div className="article-list">
        {articles.length ? articles.map((article) => (
          <article className="article-row" key={article.safe_name || article.full_name || article.project}>
            <div className="article-row-main">
              <h3>{articleTitle(article, language)}</h3>
              <div className="article-meta">
                <span>{t.labels.project}: {article.full_name || article.project || "-"}</span>
                <span>{t.labels.words}: {article.word_count ?? article.words ?? "-"}</span>
                <span>{t.labels.reviewScore}: {article.review_score ?? article.reviewScore ?? "-"}</span>
                {article.quality_score != null ? (
                  <span>
                    {t.labels.qualityScore}: {article.quality_score} ·{" "}
                    {article.quality_publish_ready ? t.labels.publishable : t.labels.needsRevision}
                  </span>
                ) : null}
                {article.generation_mode ? <span>{t.labels.generationMode}: {article.generation_mode}</span> : null}
                {article.narrative_pattern ? <span>{t.labels.narrativePattern}: {article.narrative_pattern}</span> : null}
                <span>{t.labels.contentPlanUsed}: {article.content_plan_used ? "yes" : "no"}</span>
                <span>{t.labels.humanized}: {article.humanized ? "yes" : "no"}</span>
                {article.ai_smell_score != null ? <span>{t.labels.naturalness}: {article.ai_smell_score}</span> : null}
                {article.template_risk != null ? <span>{t.labels.templateRisk}: {article.template_risk}</span> : null}
                {article.localization_score != null ? <span>{t.labels.localizationScore}: {article.localization_score}</span> : null}
              </div>
            </div>
            <div className="row-actions">
              <button className="icon-text-button" type="button" onClick={() => onPreview(article)}>
                <Eye size={16} aria-hidden="true" />
                <span>{loadingArticle === article.safe_name ? t.actions.loading : t.actions.preview}</span>
              </button>
              <button
                className="icon-button"
                type="button"
                aria-label={t.actions.download}
                title={t.actions.download}
                onClick={() => onDownload(article)}
              >
                <Download size={16} aria-hidden="true" />
              </button>
            </div>
          </article>
        )) : <p className="empty-state">{t.empty.noFinalArticles}</p>}
      </div>
    </section>
  );
}
