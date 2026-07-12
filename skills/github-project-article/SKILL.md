---
name: github-project-article
description: Use this skill when the user wants to discover GitHub open-source projects, write a WeChat/public-account article about a GitHub repository, generate daily GitHub project articles, package article assets, or improve GitHub project article quality.
---

# GitHub 项目文章 Skill

## 适用场景

- 用户给出 GitHub 仓库链接，要求写一篇公众号项目文章。
- 用户要求自动发现 GitHub 开源项目，并筛选、研究、写作。
- 用户要求生成开源项目日报或每日项目推荐。
- 用户要求优化 GitHub 项目文章质量、发布包、配图或公众号可发布形态。

## 不适用场景

- AI 新闻文章不使用本 skill，改用 `ai-news-article`。
- 纯代码开发、Bug 修复、工程重构、测试补齐等任务不使用本 skill。

## 快速决策

- 用户提供 repo URL：优先走 `write-custom`。
- 用户没有提供 repo URL：走 `discover -> score -> select-projects`，再进入研究和写作。
- 用户要求不重复：检查 `article_history` 和 `selection_latest`，必要时扩大候选范围或冷却期。
- 文章没有发布包：调用 `package-articles`。
- 文章质量低：调用 review、polish、quality 相关能力重新评估和改写。

## 必读 References

- `references/workflow.md`：执行流程、异常处理和 Agent 自主判断。
- `references/quality_rules.md`：文章质量、标题、配图、发布和禁用表达规则。
- `references/cli_api_mapping.md`：当前 CLI/API 能力映射。

## 输出要求

- Markdown 文章正文。
- 质量报告或评估摘要。
- 发布包，包括公众号可用 Markdown 和图片资源。
- 清晰列出产物路径，便于用户打开、复查和发布。

## 关键边界

- 不搬运 README，不把仓库说明改写成流水账。
- 不使用“发现一个多少 star 项目”旧模板。
- 重点写项目特点、作用、效果和具体例子。
- 发布文章只保留项目地址，不堆参考链接。
- README 有图时优先使用 README 图；没有图可用 GitHub 截图；都没有时保持纯文字，不强行生成装饰图。
