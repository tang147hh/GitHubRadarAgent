# GitHubRadarAgent 示例输出说明

当前示例输出位于：

```text
outputs/2026-07-01/
workspace/runs/latest_run.json
```

这些文件用于展示完整日报流程的运行结果，也方便复盘每个阶段的输入和输出。

## 核心示例文件

| 文件 | 说明 |
| --- | --- |
| `workspace/runs/latest_run.json` | 最新一次 `run-daily` 的结构化运行状态，包含 run id、日期、阶段状态、耗时、错误和产物路径。 |
| `outputs/2026-07-01/daily_report.md` | 每日运行报告，适合展示整体流水线是否成功、各阶段耗时和当次终稿文章。 |
| `outputs/2026-07-01/score_report.md` | 候选项目评分报告，展示多维评分排序和入选理由。 |
| `outputs/2026-07-01/research_notes.md` | Top 项目的结构化调研笔记，包含 README 摘要、release、issue 和风险提示。 |
| `outputs/2026-07-01/topic_angles.md` | 公众号选题角度、目标读者、标题候选、开头钩子和大纲。 |
| `outputs/2026-07-01/article_drafts.md` | 公众号文章初稿汇总。 |
| `outputs/2026-07-01/review_report.md` | 编辑评审报告，包含事实、标题、结构、可读性和完整度评分。 |
| `outputs/2026-07-01/final_articles_index.md` | 当次终稿索引，列出项目、标题、评审分数和终稿路径。 |
| `outputs/2026-07-01/final_articles/` | 终稿 Markdown 文件目录。 |

## 当前示例运行摘要

`workspace/runs/latest_run.json` 显示最新一次运行：

- Run ID：`daily_20260701_135801`
- 日期：`2026-07-01`
- 状态：`success`
- 流程：`discover -> score -> research -> angles -> write-articles -> review-articles`
- 发现候选项目：5 个
- 评分项目：5 个
- 当次调研项目：1 个
- 当次生成选题：1 个
- 当次生成初稿：1 篇
- 当次评审并保存终稿：1 篇

`daily_report.md` 和 `final_articles_index.md` 的“今日终稿文章 / 终稿列表”代表当次运行进入终稿索引的文章。`final_articles/` 目录中可能保留同一天早先运行产生的其他 Markdown 文件；这些历史文件不会删除，展示时应以索引文件为准。

## 展示建议

推荐按以下顺序展示：

1. 打开 `README.md` 说明项目目标和能力边界。
2. 打开 `outputs/2026-07-01/daily_report.md` 展示全流程已经跑通。
3. 打开 `outputs/2026-07-01/research_notes.md` 展示调研阶段不是凭空写作。
4. 打开 `outputs/2026-07-01/topic_angles.md` 展示选题策划能力。
5. 打开 `outputs/2026-07-01/review_report.md` 展示 Reflection / 编辑评审。
6. 打开 `outputs/2026-07-01/final_articles_index.md` 和 `final_articles/` 展示最终 Markdown 文章。
7. 打开 `docs/TECHNICAL_MAPPING.md` 说明教程技术点如何落地。

## 注意事项

- 示例输出是本地 Markdown / JSON 文件，不代表已经发布到公众号。
- 文章终稿仍需人工复核事实、标题尺度和发布风格。
- `.env` 中的真实密钥不应展示、提交或复制到文档中。
- 如果重新运行 `run-daily`，`*_latest.json` 会被更新，日期目录也会按运行日期生成或覆盖同名报告。
