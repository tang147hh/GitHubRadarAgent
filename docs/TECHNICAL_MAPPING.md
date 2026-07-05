# GitHubRadarAgent 教程技术映射

本文档说明 GitHubRadarAgent 如何把 Hello-Agents 教程中的 Agent 思想落到一个可运行、可复盘的本地 CLI 项目中。

## 总体设计

GitHubRadarAgent 采用分阶段 Agent 工作流：

```text
discover -> score -> research -> angles -> write-articles -> review-articles
```

每个阶段都有清晰输入、处理逻辑和输出文件。`run-daily` 负责统一编排，`workspace/runs/latest_run.json` 记录每个阶段的状态、耗时、错误和关键产物路径。

## ReAct 映射

ReAct 的核心思想是让 Agent 在任务执行中交替进行观察、推理和行动。本项目中的落地方式：

| ReAct 要素 | 项目实现 |
| --- | --- |
| Observe | `discover` 从 GitHub Search API 获取候选项目；`research` 获取 README、release、issue 等资料。 |
| Reason | `score` 根据热度、相关度、质量、活跃度和传播潜力进行排序；`angles` 判断公众号切入点。 |
| Act | 各阶段写入 JSON 快照和 Markdown 报告，形成可追踪产物。 |
| Trace | `workspace/snapshots` 和 `outputs/YYYY-MM-DD` 保留中间结果，方便复盘每一步判断。 |

对应代码：

- `src/discovery.py`
- `src/github_client.py`
- `src/research.py`
- `src/scoring.py`
- `src/orchestrator.py`

## Plan-and-Solve 映射

Plan-and-Solve 的核心是先拆解复杂任务，再逐步完成。GitHubRadarAgent 将“生成每日 AI 项目公众号推荐”拆为六个稳定阶段：

| 阶段 | 输入 | 输出 | 作用 |
| --- | --- | --- | --- |
| discover | 关键词、GitHub API | `discovery_latest.json` | 找到候选项目 |
| score | 候选项目快照 | `score_latest.json`、`score_report.md` | 选出更值得写的项目 |
| research | Top 项目 | `research_latest.json`、`research_notes.md` | 沉淀事实资料 |
| angles | 调研笔记 | `angles_latest.json`、`topic_angles.md` | 形成公众号选题 |
| write-articles | 调研笔记、选题角度 | `articles_latest.json`、`article_drafts.md` | 生成初稿 |
| review-articles | 初稿、调研笔记、选题角度 | `reviews_latest.json`、`final_articles/` | 评审并产出终稿 |

`src/orchestrator.py` 中的 `run_daily()` 是主编排入口。它按固定顺序执行各阶段，并在阶段失败时记录错误状态。

## Reflection 映射

Reflection 的核心是让 Agent 对前一步结果进行独立评估和修正。本项目体现在 `review-articles`：

- 对文章初稿进行独立编辑评审。
- 评分维度包括事实风险、标题质量、结构完整度、公众号可读性和信息完整度。
- 评审报告写入 `outputs/YYYY-MM-DD/review_report.md`。
- 终稿写入 `outputs/YYYY-MM-DD/final_articles/`。
- LLM 不可用或返回异常时，使用启发式 fallback，避免流程中断。

对应代码：

- `src/editor.py`
- `src/article_writer.py`
- `src/llm_service.py`
- `src/orchestrator.py`

## 工具调用映射

| 工具 / 能力 | 项目实现 | 用途 |
| --- | --- | --- |
| GitHub REST API | `src/github_client.py` | 搜索项目、读取仓库详情、README、release、issue。 |
| OpenAI-compatible LLM | `src/llm_service.py` | 生成选题角度、文章初稿和编辑评审。 |
| 本地文件系统 | `workspace/`、`outputs/` | 保存快照、笔记、报告和终稿。 |
| Typer / argparse fallback | `main.py` | 提供 CLI 命令入口。 |
| schedule | `main.py` | 提供本地每日定时任务。 |

## 记忆与复盘映射

本项目使用本地文件作为轻量记忆：

- `workspace/snapshots/*_latest.json`：最新阶段数据。
- `workspace/snapshots/YYYY-MM-DD-*.json`：按日期保存的阶段快照。
- `workspace/runs/latest_run.json`：最新一次 `run-daily` 的阶段状态。
- `workspace/notes/`：单项目调研笔记。
- `workspace/articles/`：单项目文章初稿。
- `outputs/YYYY-MM-DD/`：面向展示与复盘的 Markdown 产物。

这种方式让每次运行都可以被追踪、比较和人工复核。

## 工程化映射

| 工程能力 | 项目实现 |
| --- | --- |
| 配置管理 | `.env.example`、`python-dotenv`、`src/config.py` |
| 数据结构 | `src/models.py`、Pydantic |
| CLI 入口 | `main.py`、Typer |
| 可观测运行状态 | `workspace/runs/latest_run.json`、`daily_report.md` |
| 降级策略 | LLM 不可用时使用启发式 fallback |
| 安全边界 | `.env` 被 `.gitignore` 忽略，README 不展示真实 token |

## 当前边界

- 当前版本是 CLI + 本地 Markdown，不包含前端。
- 当前版本不接公众号 API，不自动发布。
- 当前趋势判断主要基于 GitHub 当前元信息和启发式评分，尚未实现长期 star 增长统计。
- 当前事实来源主要是 GitHub README、release 和 issue，发布前仍需要人工复核。
