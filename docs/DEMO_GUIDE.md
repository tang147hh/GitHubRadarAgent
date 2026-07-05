# GitHubRadarAgent 演示指南

## 演示目标

这个项目演示：

- 自动发现 GitHub AI/Agent 项目
- 自动评分调研
- 自动生成公众号文章
- Web 控制台实时运行和查看产物

## 演示前准备

1. 配置 `.env`

```bash
cp .env.example .env
```

按需填写：

```bash
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
GITHUB_PERSONAL_ACCESS_TOKEN=
OUTPUT_DIR=outputs
WORKSPACE_DIR=workspace
DAILY_KEYWORDS=ai agent,llm agent,mcp,rag,multi-agent,workflow automation
```

2. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. 安装前端依赖

```bash
cd frontend
pnpm install
```

如果没有 `pnpm`：

```bash
cd frontend
npm install
```

4. 确认已有 `outputs` 样例

```bash
ls outputs
ls outputs/2026-07-02
```

重点确认：

```text
outputs/YYYY-MM-DD/daily_report.md
outputs/YYYY-MM-DD/final_articles_index.md
outputs/YYYY-MM-DD/final_articles/
workspace/runs/latest_run.json
```

## 启动后端

```bash
python3 api_server.py
```

后端默认地址：

```text
http://127.0.0.1:8000
```

快速检查：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/dashboard
```

## 启动前端

另开终端：

```bash
cd frontend
pnpm run dev
```

如果使用 npm：

```bash
cd frontend
npm run dev
```

前端默认地址：

```text
http://127.0.0.1:5173
```

## 演示路径

1. 打开 Web 控制台首页，确认 Dashboard 能展示最近运行、候选项目、评分和终稿信息。
2. 进入 Candidates 页面，展示自动发现的 GitHub 项目列表。
3. 进入 Score Ranking 页面，展示多维评分排序。
4. 进入 Research Notes 页面，展示 README/release/issue 调研摘要。
5. 进入 Topic Angles 页面，展示公众号选题角度和标题候选。
6. 进入 Articles 页面，打开终稿 Markdown，演示复制、下载和 GitHub 链接。
7. 进入 Reviews 页面，展示编辑评审结果。
8. 进入 Reports 页面，打开 `daily_report.md`、`score_report.md`、`review_report.md` 和 `final_articles_index.md`。
9. 进入 Runs History 页面，展示最近运行和历史阶段状态。
10. 进入 Settings 页面，展示默认运行参数、关键词和语言配置；说明页面不展示真实密钥。

## 演示实时运行

在 Web 控制台点击 Run Daily。

建议演示参数：

```text
limit_per_keyword: 1
score_top: 3
research_top: 1
article_top: 1
review_threshold: 80
```

观察点：

- Pipeline Progress 会显示 `discover -> score -> research -> angles -> write-articles -> review-articles`。
- Run Logs 会显示后台任务日志。
- 优先使用 SSE 实时进度；不可用时前端会自动轮询。
- 运行完成后 Dashboard、Runs History 和 Reports 可以刷新查看新产物。

## CLI 演示

查看命令：

```bash
python3 main.py --help
```

运行轻量日报：

```bash
python3 main.py run-daily --limit-per-keyword 1 --score-top 3 --research-top 1 --article-top 1
```

查看产物：

```bash
cat workspace/runs/latest_run.json
ls outputs/$(date +%F)
```

## QA 检查

运行最终 QA：

```bash
python3 scripts/qa_check.py
```

脚本会检查：

- 关键文件和目录
- 常见密钥前缀和非空密钥配置
- Python 编译
- 前端 package 配置
- 本地运行产物

报告输出到：

```text
docs/QA_REPORT.md
```

## 演示边界

- 不自动发布公众号。
- 不接公众号 API。
- `.env` 只保存在本地，不提交、不展示。
- Web API 只返回密钥是否已配置，不返回真实密钥内容。
- 不配置 LLM 时，写作和评审会使用 fallback，保证流程可演示。
