# GitHub 项目文章 CLI/API Mapping

## CLI

- `python3 main.py run-daily`：运行完整每日 GitHub 项目文章流程。
- `python3 main.py discover`：发现 GitHub 仓库候选。
- `python3 main.py score`：对候选仓库评分。
- `python3 main.py research`：研究评分靠前或选中的仓库。
- `python3 main.py plan-content`：生成文章策划。
- `python3 main.py write-articles`：写作每日项目文章。
- `python3 main.py review-articles`：评估每日项目文章。
- `python3 main.py package-articles`：生成发布包和图片资源。
- `python3 main.py write-custom`：根据指定仓库或方向写自定义项目文章。

## API

- `POST /api/run-daily/async`：异步启动每日完整流程。
- `GET /api/jobs/{job_id}`：查询异步任务状态。
- `GET /api/dashboard`：读取仪表盘数据和最新流程结果。
- `GET /api/articles/final`：读取最终文章列表。
- `GET /api/articles/package/{safe_name}`：读取指定文章发布包。
- `POST /api/articles/package`：为文章生成发布包。
- `POST /api/custom-articles/async`：异步生成自定义项目文章。
- `GET /api/custom-articles/latest`：读取最新自定义文章元数据。
- `GET /api/custom-articles/latest/content`：读取最新自定义文章正文。
- `GET /api/custom-articles/latest/package`：读取最新自定义文章发布包。
