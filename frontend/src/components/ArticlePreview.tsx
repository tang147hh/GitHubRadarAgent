import ReactMarkdown from "react-markdown";
import { ExternalLink } from "lucide-react";
import type { Language, Translation } from "../i18n";
import { markdownImageSrc } from "../markdownImages";

type ArticlePreviewProps = {
  t: Translation;
  language: Language;
  title?: string;
  markdown?: string;
  intro?: string;
  projectUrl?: string;
  sourcePath?: string;
  loading?: boolean;
};

export function ArticlePreview({ t, language, title, markdown, intro, projectUrl, sourcePath, loading = false }: ArticlePreviewProps) {
  return (
    <section className="panel article-preview-panel">
      <div className="panel-header">
        <h2>{t.sections.articlePreview}</h2>
        {sourcePath ? <span className="soft-badge unknown">{sourcePath}</span> : null}
      </div>

      <article className="markdown-preview markdown-body">
        <h3>{loading ? t.actions.loading : title || t.empty.noPreviewTitle}</h3>
        {intro ? <p className="preview-intro">{intro}</p> : null}
        {markdown ? (
          <ReactMarkdown
            components={{
              img: ({ src, alt, ...props }) => (
                <img {...props} alt={alt || ""} src={markdownImageSrc(src, sourcePath || "")} />
              ),
            }}
          >
            {markdown}
          </ReactMarkdown>
        ) : (
          <p className="empty-state">{language === "zh" ? "请选择一篇终稿或报告进行预览。" : "Select a final article or report to preview."}</p>
        )}
        {projectUrl ? <a className="project-link" href={projectUrl} target="_blank" rel="noreferrer">
          <ExternalLink size={16} aria-hidden="true" />
          <span>{projectUrl}</span>
        </a> : null}
      </article>
    </section>
  );
}
