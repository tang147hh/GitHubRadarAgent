# GitHubRadarAgent 最终验收清单

本文档用于最终验收：完善项目文档、示例输出、教程技术映射、Web 控制台与最终 QA。

## 文档验收

- [x] README 已说明 GitHubRadarAgent 是什么、解决什么问题、面向谁使用。
- [x] README 已明确第一版能力边界：CLI + 本地 Markdown，不自动发布公众号。
- [x] README 已列出核心功能：项目发现、评分、调研、选题、写作、评审、`run-daily`、`schedule`。
- [x] README 已列出技术栈：Python、Typer / Rich、Pydantic、requests、python-dotenv、schedule、GitHub REST API、OpenAI-compatible LLM、ReAct / Plan-and-Solve / Reflection。
- [x] README 已提供快速开始命令。
- [x] README 已说明 `.env` 用途和安全注意事项。
- [x] README 已区分已完成能力和后续规划。
- [x] 已新增教程技术映射文档：`docs/TECHNICAL_MAPPING.md`。
- [x] 已新增示例输出说明：`docs/SAMPLE_OUTPUTS.md`。
- [x] 已新增演示指南：`docs/DEMO_GUIDE.md`。
- [x] 已新增 QA 报告输出：`docs/QA_REPORT.md`。

## 产物验收

- [x] `workspace/runs/latest_run.json` 存在。
- [x] `outputs/2026-07-01/daily_report.md` 存在。
- [x] `outputs/2026-07-01/final_articles/` 存在。
- [x] `outputs/2026-07-01/final_articles_index.md` 存在。
- [x] `outputs/2026-07-01/review_report.md` 存在。
- [x] 示例输出说明已解释当次索引与目录历史文件的区别。

## 安全验收

- [x] `.gitignore` 已忽略 `.env` 和 `.env.*`，并保留 `.env.example`。
- [x] `.env.example` 只包含空占位配置。
- [x] README 不包含真实 token。
- [x] 文档不要求提交或展示 `.env`。

## 运行验收

建议最终验证命令：

```bash
python3 main.py --help
python3 scripts/qa_check.py
python3 main.py run-daily --limit-per-keyword 1 --score-top 3 --research-top 1 --article-top 1
```

通过标准：

- `python3 main.py --help` 能正常显示 CLI 命令。
- `python3 scripts/qa_check.py` 输出 `PASS`，并生成 `docs/QA_REPORT.md`。
- `run-daily` 能完整执行 `discover -> score -> research -> angles -> write-articles -> review-articles`。
- 运行后 `workspace/runs/latest_run.json` 的 `status` 为 `success`。
- 运行后生成或更新 `outputs/YYYY-MM-DD/daily_report.md`。
- 运行后生成或更新 `outputs/YYYY-MM-DD/final_articles_index.md`。
- 运行后生成或更新 `outputs/YYYY-MM-DD/review_report.md`。

## 本次验证记录

- [x] 已执行 `python3 main.py --help`，CLI 命令可正常显示。
- [x] 已执行 `python3 scripts/qa_check.py`，QA 脚本可生成 Markdown 报告。
- [x] 已执行 `python3 main.py run-daily --limit-per-keyword 1 --score-top 3 --research-top 1 --article-top 1`。
- [x] 最新 Run ID：`daily_20260701_161006`。
- [x] 最新运行状态：`success`。
- [x] 六个阶段均成功：`discover`、`score`、`research`、`angles`、`write-articles`、`review-articles`。
- [x] 已生成或更新 `workspace/runs/latest_run.json`。
- [x] 已生成或更新 `outputs/2026-07-01/daily_report.md`。
- [x] 已生成或更新 `outputs/2026-07-01/final_articles_index.md`。
- [x] 已生成或更新 `outputs/2026-07-01/review_report.md`。
- [x] 验证时未使用本地 `.env` 中的 LLM 或 GitHub token；未认证 GitHub API 触发 rate limit 后，流程按设计记录风险并继续完成。

## 第 17 步最终 QA

- [x] 已新增 `scripts/qa_check.py`。
- [x] QA 脚本不启动后端或前端 server。
- [x] QA 脚本不访问网络。
- [x] QA 脚本不读取 `.env`。
- [x] QA 脚本检查关键文件、敏感信息、Python 编译、前端 package 和本地产物。
- [x] 已新增 `docs/DEMO_GUIDE.md`，覆盖后端、前端、CLI、实时运行和 QA 演示路径。
- [x] 已保留第一版边界：不自动发布公众号，不接公众号 API。

## 当前未纳入验收的后续规划

- 不验收公众号 API 发布。
- 不验收云部署、后台任务队列或 cron 部署。
- 不验收长期 star 增长数据库。
- 不验收多平台内容分发。
