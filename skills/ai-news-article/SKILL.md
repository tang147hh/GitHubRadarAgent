---
name: ai-news-article
description: Use this skill when the user wants to collect AI news, translate and classify AI news, select news items, inspect news details, generate an AI news digest, or write a WeChat/public-account article from selected AI news.
---

# AI 新闻文章 Skill

## 适用场景

- 用户要求报道每日 AI 圈新闻。
- 用户要求从 AI 新闻列表选题写公众号文章。
- 用户要求生成 AI 新闻日报。
- 用户要求查看新闻详情、翻译新闻、评分分类或筛选新闻。

## 不适用场景

- GitHub 开源项目分享文章不使用本 skill，改用 `github-project-article`。

## 快速决策

- 用户要日报：走 `collect-news -> score-news -> build-news-events -> write-news-digest -> review-news-digest`。
- 用户要单篇新闻文章：走 `fetch detail -> select-news -> plan-news-article -> write-news-article -> review-news-article`。
- 新闻只有标题：先执行 `fetch-news-detail` 或 refresh，补齐正文、摘要和来源信息。
- 用户选择多条新闻：设定主新闻，并把其他新闻作为 supporting sources。

## 必读 References

- `references/workflow.md`：采集、日报、单篇文章和前端交互流程。
- `references/source_rules.md`：新闻来源、新鲜度、正文可用性、互动数量和版权边界。
- `references/quality_rules.md`：日报和单篇文章质量规则、禁用表达和事实边界。
- `references/cli_api_mapping.md`：当前 CLI/API 能力映射。

## 关键边界

- 不搬运原文。
- 不编造事实、细节、结论或未发生的影响。
- 不根据点赞数、评论数、points、comments 写文章。
- 有价值评论正文可以作为补充参考，但互动数量完全忽略。
- 单篇新闻文章不要二级标题和机械分点。
- 保留原文链接，方便用户核查来源。
