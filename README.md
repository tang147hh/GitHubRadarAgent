# GitHubRadarAgent

GitHubRadarAgent 是一个面向 AI / Agent 开源项目追踪与公众号选题生产的本地 CLI Agent。它会从 GitHub 发现近期值得关注的 AI / Agent 项目，进行多维评分、资料调研、选题策划、公众号文章初稿生成，并通过编辑评审产出可供人工复核的 Markdown 终稿。

这个项目解决的问题是：当创作者、技术编辑或开发者需要持续关注 GitHub 上的 AI / Agent 新项目时，手动搜索、筛选、读 README、判断传播价值、写公众号稿件非常耗时。GitHubRadarAgent 把这些步骤串成一个可复盘的本地流水线，帮助用户更快得到“候选项目 + 调研笔记 + 选题角度 + 文章终稿 + 运行报告”。

当前第一版能力边界很明确：提供 CLI、本地 Markdown / JSON 输出、FastAPI 本地服务和 React Web 控制台。不自动发布公众号，不接公众号 API。所有文章终稿都应先由人工复核后再发布。

## 核心功能

- GitHub AI / Agent + 实用工具类项目发现：默认围绕 `ai agent`、`llm agent`、`mcp`、`rag`、`multi-agent`、`workflow automation`、`developer tools`、`productivity tool`、`cli tool`、`self-hosted`、`automation tool`、`chrome extension`、`terminal tool` 等关键词搜索候选仓库；用户可在 Settings 页面删改关键词。
- 多维评分排序：综合 star / fork、AI 相关度、基础质量、维护活跃度和公众号传播潜力排序。
- README / release / issue 深度调研：抓取仓库元信息、README、最新 release 和 open issue 样本，生成结构化调研笔记。
- 作者/组织与项目链接抽取：通过 GitHub API 补充作者/组织背景，并从 README 中抽取 homepage、docs、demo、examples、图片、视频和 badge 链接。
- 公众号选题角度和爆款标题生成：为 Top 项目生成目标读者、传播卖点、标题候选、开头钩子和文章大纲。
- 内容策划中间产物：在写文章前生成 FactCard、ProjectInsight 和 EditorialBrief，新增主编策略与可变叙事建议，降低 README 搬运和模板稿风险。
- 公众号文章初稿生成：优先基于 FactCard、ProjectInsight、EditorialBrief、NarrativeStrategy 和 TitleStrategy 生成本地 Markdown 初稿；缺少内容策划快照时仍兼容旧输入。
- 编辑评审与反思优化：检查事实风险、标题质量、结构完整度、可读性和信息完整度，输出终稿。
- 去 AI 味编辑器：在终稿后增加二次质量检查和必要改写，降低模板句式、README 搬运、机械翻译、固定小标题和总结腔带来的阅读割裂感。
- 公众号文章质量评估器：在发布清理后为每篇终稿生成 0-100 分的公众号质量报告，判断标题、开头、项目价值、具体例子、效果展开、可读性、人味表达、README 搬运感和公众号结构是否达到“值得发”的标准。
- 文章配图与发布包：优先从项目 README 中挑选已有图片插入 `packaged_article.md`；README 没有合适图片时，可选使用真实 GitHub README 页面或仓库首页截图作为 fallback；截图依赖不可用或截图失败时仍生成纯文字发布包。
- 指定 GitHub 项目写作：输入任意 GitHub 仓库地址，直接走“调研 -> 内容规划 -> 写作 -> 评审 -> 去 AI 味 -> 发布清理 -> 输出”的单项目主链路。
- 一键 `run-daily`：串联 `discover -> score -> research -> angles -> plan-content -> write-articles -> review-articles`。
- 本地 `schedule` 定时任务：使用本地常驻 Python 进程按指定时间触发每日运行。

## 技术栈

- Python
- Typer / Rich
- Pydantic
- requests
- python-dotenv
- schedule
- GitHub REST API
- OpenAI-compatible LLM
- Hello-Agents 教程中的 ReAct / Plan-and-Solve / Reflection 思想

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑本地 `.env`，按需填写：

```bash
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
GITHUB_PERSONAL_ACCESS_TOKEN=
OUTPUT_DIR=outputs
WORKSPACE_DIR=workspace
DAILY_KEYWORDS=ai agent,llm agent,mcp,rag,multi-agent,workflow automation,developer tools,productivity tool,cli tool,self-hosted,automation tool,chrome extension,terminal tool
```

说明：

- `.env` 只用于本地运行，不要提交。
- `.env.example` 只保留空占位配置，不包含真实 token。
- 不配置 GitHub token 时也可以低频调用 GitHub API，但更容易遇到 rate limit。
- 不配置 LLM 时，选题、写作和评审会使用启发式 fallback，保证流程可跑通。
- GitHub 页面截图是可选能力。若需要 README 无图时自动截图，可安装 Python Playwright 并初始化浏览器：`pip install playwright && python3 -m playwright install chromium`；如果只运行 Web 前端，也可复用前端 `playwright` 依赖。缺少截图依赖不会导致文章生成失败。

运行完整日报：

```bash
python3 main.py run-daily --limit-per-keyword 3 --score-top 10 --research-top 3 --article-top 3
```

运行后重点查看：

```text
workspace/runs/latest_run.json
outputs/YYYY-MM-DD/daily_report.md
outputs/YYYY-MM-DD/final_articles_index.md
outputs/YYYY-MM-DD/final_articles/
outputs/YYYY-MM-DD/review_report.md
outputs/YYYY-MM-DD/article_quality_report.md
```

## CLI 命令

```bash
python3 main.py discover --limit-per-keyword 5
python3 main.py score --top 10
python3 main.py research --top 3
python3 main.py angles --top 3
python3 main.py plan-content --top 3
python3 main.py write-articles --top 3
python3 main.py review-articles --top 3 --threshold 80
python3 main.py humanize-articles --top 3
python3 main.py polish-for-publish --top 3
python3 main.py package-articles --top 3
python3 main.py write-custom --repo-url https://github.com/sharkdp/bat
python3 main.py run-daily --limit-per-keyword 3 --score-top 10 --research-top 3 --article-top 3
python3 main.py schedule --time 09:00
python3 main.py schedule --time 09:00 --run-once-first
```

`articles` 是 `write-articles` 的兼容别名。`write --repo owner/name` 仍是早期占位命令，不属于当前日报主流程。

### 指定 GitHub 项目写作

`write-custom` 用于给指定仓库单独生成一篇公众号发布稿，不走 `discover / score / angles` 的批量流程，也不会覆盖每日批量文章快照。

支持的仓库输入格式：

```text
https://github.com/owner/repo
http://github.com/owner/repo
github.com/owner/repo
owner/repo
```

运行示例：

```bash
python3 main.py write-custom --repo-url https://github.com/sharkdp/bat
python3 main.py write-custom --repo-url owner/repo --direction "从 CLI 使用体验切入"
python3 main.py write-custom --repo-url owner/repo --direction "从程序员日常使用体验写，不要太像教程"
python3 main.py write-custom --repo-url owner/repo --direction "重点写它为什么适合命令行用户，标题口语一点"
python3 main.py write-custom --repo-url owner/repo --direction "先写适合谁" --direction-file notes/direction.md
python3 main.py write-custom --repo-url https://github.com/sharkdp/bat --direction "从程序员日常体验写" --reference-file examples/style.md
python3 main.py write-custom --repo-url owner/repo --reference-text "这里粘贴一篇参考文章，用于分析语气、节奏和标题倾向"
```

如果同时传入 `--direction` 和 `--direction-file`，系统会合并两段方向文本，命令行文本在前，文件内容在后。系统会把方向文本解析成结构化写作约束，包括目标读者、写作视角、核心角度、必写重点、避免内容、语气偏好、标题偏好和内容取舍，并用于影响选题角度、内容规划、标题、正文写法、去 AI 味和发布清理。

`write-custom` 还支持风格参考：

- `--reference-file path/to/article.md`：读取本地 `.md` / `.txt` 参考文章，可重复传多次。
- `--reference-text "参考文章内容"`：直接传入参考文章文本，也可重复传多次。

参考文章只用于生成结构化风格画像，影响语气、节奏、读者关系、开头方式和标题倾向；不会复制原文内容、句子、标题、独特比喻、段落顺序或核心表达。系统会把参考材料限定为“原创风格参考”：direction 决定写什么，style reference 只决定怎么写，项目事实和 ProjectAppeal 决定凭什么写。输出报告只展示风格画像摘要、原创性规则和简短风险片段，不展示完整参考文章原文。

当提供 `--reference-file` 或 `--reference-text` 时，`write-custom` 会在发布清理后执行原创性检查与相似度保护：

- 检查标题是否与参考标题过近。
- 检查连续相同字符或 token 片段长度。
- 检查完整句子重复数量。
- 检查段落数量和段落长度节奏是否高度接近。
- 检查参考文章中的独特表达是否被复用。
- 如发现风险，最多自动改写一次，目标是保留项目事实和用户方向，同时避免复制原句、标题和段落结构。

不提供参考文章时，快照中的 `originality_report.checked=false`，并记录“未提供参考文章，本次未执行相似度检查”。

主要产物：

```text
outputs/YYYY-MM-DD/custom_articles/owner__repo.md
outputs/YYYY-MM-DD/custom_articles/owner__repo_report.md
outputs/YYYY-MM-DD/assets/owner__repo/packaged_article.md
outputs/YYYY-MM-DD/assets/owner__repo/assets.json
workspace/snapshots/custom_article_latest.json
workspace/snapshots/YYYY-MM-DD-custom-article-owner__repo.json
```

终稿 Markdown 会经过发布清理，只在文末保留一个项目地址，不输出参考链接堆、阅读提示或 README 搬运式说明。`write-custom` 也会生成与系统发现文章一致的发布包：优先使用 README 中已有的合适图片；README 没有合适图片时尝试截取真实 GitHub README 页面，失败后再尝试仓库首页截图；截图也失败时仍生成纯文字 `packaged_article.md`；不会自动生成 SVG、AI 图或装饰图。JSON 快照会记录 `repo_url`、`full_name`、`direction_text`、`custom_direction` / `parsed_direction`、`style_reference_profile`、`reference_source_names`、`reference_text_count`、`research_note`、`content_plan`、`draft`、`review`、`final_article`、`humanization_report`、`publish_polish_report`、`article_quality_report`、`quality_score`、`quality_publish_ready`、`originality_report`、`originality_checked`、`originality_passed`、`package_path`、`packaged_article_available`、`selected_readme_images`、`visual_assets` 和 `asset_count`，便于复盘。报告文件会展示原始方向文本、解析结果、风格画像摘要、方向遵守情况、文章质量评分、原创性检查结果和配图来源，但不会展示完整参考文章原文。

## 指定项目写作 Web 页面

React 控制台新增“指定项目写作 / Custom Article”页面，把 `write-custom` 主链路接入网页。用户可以在页面中输入 GitHub URL、填写文章方向、粘贴风格参考文本，或选择本地 `.md` / `.txt` 参考文件。参考文件只在浏览器端读取文本后随请求发送，不会上传保存到项目目录。生成结果会展示“原创性检查 / Originality Check”，包括是否通过、相似度风险、是否自动改写和简短问题列表。

启动方式：

```bash
python3 api_server.py
cd frontend && pnpm run dev
```

打开 `http://127.0.0.1:5173`，在侧边栏进入“指定项目写作”。页面能力包括：

- 输入 GitHub URL，例如 `https://github.com/sharkdp/bat`。
- 填写文章方向，让系统围绕指定读者、语气和内容取舍生成文章。
- 提供参考文章风格，系统只提取风格画像，用于原创表达、避免复制原句和结构，并提供相似度保护。
- 查看实时进度和运行日志。
- 完成后预览、复制、下载生成的公众号文章 Markdown。
- 在“文章 / 发布包 / 报告”之间切换；发布包读取最新 `packaged_article.md`，有 README 图片则展示 README 图片，没有合适图片时展示可用的 GitHub 页面截图，截图失败则展示纯文字发布稿。

Web 页面读取的最近一次结果来自：

```text
workspace/snapshots/custom_article_latest.json
outputs/YYYY-MM-DD/custom_articles/owner__repo.md
outputs/YYYY-MM-DD/custom_articles/owner__repo_report.md
outputs/YYYY-MM-DD/assets/owner__repo/packaged_article.md
```

## 发现范围

默认发现范围现在覆盖两类项目：

- AI / Agent 项目：适合做技术趋势、框架实践、Agent 应用和模型工具链类文章。
- 实用工具类开源项目：包括 CLI、开发者工具、效率工具、自托管服务、自动化工具和浏览器扩展等，更适合写成“项目分享 / 工具推荐 / 使用场景拆解”类公众号文章。

默认关键词来自 `.env` 的 `DAILY_KEYWORDS` 和 Web Settings 的 `discovery.daily_keywords`。如果 `workspace/ui_settings.json` 已存在，系统不会自动覆盖用户保存过的关键词；在 Settings 页面点击重置后会使用新的默认关键词。

## 工作流

```text
discover
  -> score
  -> research
  -> angles
  -> plan-content
  -> write-articles
  -> review-articles
```

各阶段职责：

- `discover`：调用 GitHub Search API，保存候选仓库快照。
- `score`：读取 discovery 快照，按确定性启发式规则打分排序。
- `research`：读取评分结果，抓取 README、release、issue 等资料并生成调研笔记。
- `research`：读取评分结果，抓取 README、release、issue、作者/组织资料，并从 README 抽取 docs、demo、examples、图片和视频链接；同时识别项目类型和工具使用场景。
- `angles`：根据调研笔记生成公众号选题角度、标题候选、开头钩子和大纲。
- `plan-content`：生成写作前的内容策划中间产物，包括事实卡、项目理解卡、主编 Brief、叙事策略和标题策略。该阶段已进入 `run-daily` 主链路，也可单独运行。
- `write-articles`：生成公众号推荐文章初稿。
- `review-articles`：从编辑视角评审初稿并输出终稿，随后自动运行去 AI 味、发布清理和公众号文章质量评估器。
- `humanize-articles`：读取已有终稿、初稿、调研笔记和内容计划，单独重跑去 AI 味检查与必要改写，不需要重新执行评审。
- `package-articles`：读取发布清理后的终稿，优先使用项目 README 中已有图片生成公众号发布包；没有合适图片时不插图。
- `run-daily`：自动串联 discover、score、research、angles、plan-content、write-articles、review-articles，记录运行状态和产物索引。

## 内容策划中间产物

`plan-content` 会读取 `workspace/snapshots/research_latest.json` 和可选的 `workspace/snapshots/angles_latest.json`，为每个项目生成更适合后续写作使用的结构化内容计划：

- `FactCard`：事实卡。沉淀 stars / forks、license、维护时间、技术栈、作者/组织背景、项目主页、docs/demo/examples、release、issue、来源链接、README 关键点、工具使用场景和风险提示，并标记事实是否适合直接写入文章。
- `ProjectInsight`：项目理解卡。用中文解释项目是什么、解决什么问题、核心价值、适合用户、使用场景、本土化理解和不能夸大的边界。
- `EditorialBrief`：主编 Brief。给出推荐角度、叙事模式、标题方向、开头方向、必须包含和应该避免的内容，以及后续可能需要的视觉素材。
- `ProjectAppeal`：项目吸引力卡。把功能转译成读者能感知的优势，沉淀 primary_hook、top_selling_points、feature_advantages 和 practical_scenarios，供 Writer 选择 2-3 个重点展开。
- `narrative_strategy`：主编叙事策略。根据项目类型选择 scene_first、pain_point_first、hands_on、comparison、trend_context 等叙事模式，并给出开头风格、结构风格、转场提示和需要避开的模板写法。
- `title_strategy`：标题策略。生成多角度标题候选，明确禁用“发现一个 X star 项目”“GitHub 上这个项目...”等高模板感标题，并限制 star 数只能作为辅助素材。
- `human_tone_rules` / `paragraph_plan` / `article_differentiators`：分别约束人味表达、自然段落推进和本文与常规模板的差异点。
- `writer_persona`：使用者视角 Writer 配置。默认像一个经常折腾开发工具的程序员来写，目标是激发读者兴趣、解释项目优势，并帮读者判断要不要点开项目地址。

这些主编策略会写入 `content_plan_latest.json` 和 `content_plan.md`。Writer 会优先消费这些中间产物，再生成文章；没有内容策划快照时仍兼容旧的 TopicAngle + RepoResearchNote 输入。

启用内容策划后，文章不再直接按 README 摘要搬运，也不会强制套用“这个项目是什么 / 核心亮点 / 适合谁 / 小结”等固定小节。Writer 会优先围绕 `ProjectAppeal.top_selling_points` 展开，只选择 2-3 个真正值得读者在意的优势，并把 `practical_scenarios` 自然写进项目分享里；它不会写完整教程，也不会把所有功能铺成清单。

使用者视角 Writer 的目标是“程序员在分享一个值得点开的项目”，而不是功能说明书、上手教程或 README 摘要。文章会保留 `content_plan_used`、`writer_persona`、`top_selling_points_used`、`practical_scenarios_used`、`narrative_pattern`、`title_style`、`article_style_notes` 等元信息供后续编辑阶段使用。

运行命令：

```bash
python3 main.py plan-content --top 3
```

主要产物：

```text
workspace/snapshots/content_plan_latest.json
workspace/snapshots/YYYY-MM-DD-content-plan.json
outputs/YYYY-MM-DD/content_plan.md
```

## 去 AI 味编辑器

`HumanizationEditorService` 会在终稿阶段继续检查文章是否存在 AI 模板句式、标题套路、README 搬运、机械翻译、过度均匀的段落结构、固定总结腔和中文本土化不足等问题。它会生成 `HumanizationIssue` / `HumanizationReport`，并把自然度、模板风险、README 搬运风险、本土化分和改写建议写入终稿 JSON。

当 LLM 可用且文章未通过检查时，系统会请求 LLM 做事实约束下的自然化改写；LLM 不可用时，会使用确定性 fallback 替换高频模板句、弱化旧小标题、调整套路标题，并尽量把过密列表改成自然段。该能力的目标是提升原创表达和阅读质量，不承诺规避任何平台检测。

单独运行命令：

```bash
python3 main.py humanize-articles --top 3
```

主要产物：

```text
workspace/snapshots/humanization_latest.json
workspace/snapshots/YYYY-MM-DD-humanization.json
workspace/snapshots/final_articles_latest.json
outputs/YYYY-MM-DD/humanization_report.md
outputs/YYYY-MM-DD/final_articles/
```

## 公众号文章质量评估器

`ArticleQualityEvaluator` 会在 `review-articles` 的去 AI 味和发布清理之后运行，也会在 `write-custom` 最终保存前运行。它的目标不是再做一次通用审稿，而是判断这篇 GitHub 项目分享是否真的“值得发”：标题有没有点击欲，前三段能不能留住人，项目作用和效果是否讲清楚，是否有至少两个具体例子，是否只是 README 搬运，是否太像 AI 报告、太硬核或太说明书，以及是否符合“钩子 -> 项目价值 -> 具体效果 -> 亮点展开 -> 项目地址”的公众号结构。

评分维度均为 0-100，包括 `title_score`、`opening_score`、`project_value_score`、`concrete_example_score`、`effect_depth_score`、`readability_score`、`human_tone_score`、`anti_readme_score` 和 `wechat_style_score`。`total_score >= 80` 且没有 high severity issue 时，`quality_publish_ready=true`。质量分不会阻止文章生成，也不会覆盖原有 `publish_ready`；低分文章会在报告里给出明确 warning 和可执行修改建议。

主要产物：

```text
workspace/snapshots/article_quality_latest.json
workspace/snapshots/YYYY-MM-DD-article-quality.json
outputs/YYYY-MM-DD/article_quality_report.md
outputs/YYYY-MM-DD/final_articles_index.md
outputs/YYYY-MM-DD/daily_report.md
```

## 文章配图与发布包

`run-daily` 会在 `review-articles` 后自动执行 `package-articles`，也可以手动运行 `package-articles` 或在前端 Articles 页面单篇/批量生成、重新生成发布包。`package-articles` 会读取 `workspace/snapshots/final_articles_latest.json`、`research_latest.json` 和 `content_plan_latest.json`，为每篇终稿生成可用于公众号排版的素材包：

- `packaged_article.md`：优先从项目 README 中挑选已有图片插入标题下方和正文中部，最多插入 2 张。
- `assets.json`：记录 `asset_type`、`source_url`、`output_path`、`status` 和 `error`。
- README 没有合适图片时，系统会尝试截取 GitHub README 页面；README 截图失败时再尝试仓库首页截图。
- 截图依赖不可用或截图失败时，仍生成纯文字 `packaged_article.md`，不会让整篇文章或日报失败。
- “指定 GitHub 项目写作”和系统自动发现项目写作复用同一套发布包生成链路，产物同样写入 `outputs/YYYY-MM-DD/assets/owner__repo/`。

运行命令：

```bash
python3 main.py package-articles --top 3
```

前端也提供：

- Articles 页面：单篇“生成发布包/重新生成发布包”，以及“为当前终稿生成发布包”批量操作。
- Custom Article 页面：生成完成后可直接切换查看文章、发布包和报告；如果最新结果缺少发布包，可以手动生成。
- Reports 页面：可按日期查看 `article_packages.md` 和每篇 `packaged_article.md`。

主要产物：

```text
workspace/snapshots/article_packages_latest.json
workspace/snapshots/YYYY-MM-DD-article-packages.json
outputs/YYYY-MM-DD/article_packages.md
outputs/YYYY-MM-DD/assets/owner__repo/
outputs/YYYY-MM-DD/assets/owner__repo/packaged_article.md
outputs/YYYY-MM-DD/assets/owner__repo/assets.json
outputs/YYYY-MM-DD/assets/owner__repo/github_readme_screenshot.png
outputs/YYYY-MM-DD/assets/owner__repo/github_repo_screenshot.png
```

截图服务优先使用 Python Playwright；如果不可用，会尝试使用前端依赖中的 Node Playwright（`frontend/package.json` 已包含 `playwright`）。如果本机缺少浏览器运行时，可以在前端目录执行：

```bash
pnpm install
pnpm exec playwright install chromium
```

即使 Playwright 或浏览器不可用，发布包也会降级为纯文字稿。

## 输出结构

```text
workspace/
  runs/
    latest_run.json
    daily_YYYYMMDD_HHMMSS.json
  snapshots/
    discovery_latest.json
    score_latest.json
    research_latest.json
    angles_latest.json
    content_plan_latest.json
    articles_latest.json
    reviews_latest.json
    humanization_latest.json
    publish_polish_latest.json
    article_quality_latest.json
    custom_article_latest.json
    final_articles_latest.json
    article_packages_latest.json
  notes/
    owner__repo.md
  articles/
    owner__repo.md

outputs/
  YYYY-MM-DD/
    daily_report.md
    score_report.md
    research_notes.md
    topic_angles.md
    content_plan.md
    article_drafts.md
    review_report.md
    humanization_report.md
    publish_polish_report.md
    article_quality_report.md
    article_packages.md
    custom_articles/
      owner__repo.md
      owner__repo_report.md
    articles_index.md
    final_articles_index.md
    articles/
    final_articles/
    assets/
      owner__repo/
        packaged_article.md
        assets.json
```

当前示例产物位于 `outputs/2026-07-01/`，包括日报、评分报告、调研笔记、选题角度、文章初稿、编辑评审报告和终稿目录。更详细说明见 [docs/SAMPLE_OUTPUTS.md](docs/SAMPLE_OUTPUTS.md)。

## 端到端启动

后端：

```bash
python3 api_server.py
```

前端：

```bash
cd frontend
pnpm install
pnpm run dev
```

如使用 npm：

```bash
cd frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

演示路径见 [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md)。

## 最终 QA

```bash
python3 scripts/qa_check.py
```

脚本会检查关键文件、敏感信息、Python 编译、前端 package 配置和本地产物，并写入 [docs/QA_REPORT.md](docs/QA_REPORT.md)。

## 教程技术映射

本项目不是简单调用一个模型写文章，而是把 Hello-Agents 教程中的多个 Agent 工程思想落到一个完整作品里：

- ReAct：发现、调研、记录过程体现“边观察、边判断、边写入工作区”。
- Plan-and-Solve：`run-daily` 将复杂任务拆成发现、评分、调研、选题、内容策划、写作、评审七个阶段。
- Reflection：`review-articles` 在写作后引入独立编辑视角，对事实、标题、结构和可读性做反思优化。
- 工具调用：GitHub REST API、文件快照、Markdown 报告和 OpenAI-compatible LLM 被封装为可组合能力。
- 记忆与复盘：`workspace/snapshots`、`workspace/runs` 和 `outputs` 保存每次运行的中间结果与最终产物。

完整映射见 [docs/TECHNICAL_MAPPING.md](docs/TECHNICAL_MAPPING.md)。

## 本地定时任务

```bash
python3 main.py schedule --time 09:00
python3 main.py schedule --time 09:00 --run-once-first
```

说明：

- `schedule` 是本地常驻进程，需要保持终端运行。
- 时间使用本机本地时间。
- 按 `Ctrl+C` 可以退出。
- 当前不会自动发布公众号，只会生成本地 Markdown 与 JSON 产物。

## Web API 服务

项目提供 FastAPI 后端服务，供 React Web 控制台读取真实的本地运行数据。API 只读取项目内的 `workspace/`、`outputs/` 和 `docs/` 目录，不返回 `.env` 中的任何密钥内容。

安装依赖并启动：

```bash
pip install -r requirements.txt
python3 api_server.py
```

也可以使用 reload 模式：

```bash
python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

服务默认地址：

```text
http://127.0.0.1:8000
```

常用接口：

```text
GET  /api/health
GET  /api/config/status
GET  /api/settings
PUT  /api/settings
POST /api/settings/reset
GET  /api/runs/latest
GET  /api/runs
GET  /api/snapshots/{name}
GET  /api/dashboard
GET  /api/articles/final
GET  /api/articles/final/{safe_name}?source=daily|custom
GET  /api/articles/package/{safe_name}?source=daily|custom
GET  /api/reports/{report_name}
GET  /api/custom-articles/latest/package
GET  /api/outputs/{date}
GET  /api/outputs/{date}/reports/{report_name}
GET  /api/outputs/{date}/packages/{safe_name}
POST /api/run-daily
POST /api/run-daily/async
GET  /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/events
```

### 实时运行进度

React 控制台中的 Run Daily 默认使用后台任务接口：

```bash
python3 api_server.py
```

另开终端启动前端：

```bash
cd frontend
pnpm run dev
```

说明：

- `POST /api/run-daily/async` 会立即返回 `job_id`，后端在线程池中继续执行完整日报流程。
- `GET /api/jobs/{job_id}/events` 提供 SSE 实时进度，推送 `discover`、`score`、`research`、`angles`、`write-articles`、`review-articles` 的阶段状态和日志。
- 如果 SSE 不可用，前端会自动切换为每 2 秒轮询 `GET /api/jobs/{job_id}`。
- 同步 `POST /api/run-daily` 仍保留，适合脚本或需要阻塞等待结果的调用。

### 运行配置管理

Web 控制台的 Settings 页面会通过 `workspace/ui_settings.json` 保存非敏感 UI 配置，包括默认运行参数、项目发现关键词和前端默认语言。默认结构包含：

- `run_defaults`：`limit_per_keyword`、`score_top`、`research_top`、`article_top`、`review_threshold`
- `discovery.daily_keywords`：前端可编辑的项目发现关键词
- `frontend.default_language`：`zh` 或 `en`

`GET /api/settings` 会读取该文件；文件不存在时返回内置默认值。`PUT /api/settings` 会校验数字范围、关键词数量与长度，并保存到 `workspace/ui_settings.json`。`POST /api/settings/reset` 会重置为默认配置。

安全边界：

- `workspace/ui_settings.json` 不保存 token、`OPENAI_API_KEY` 或任何真实密钥。
- GitHub Token、LLM Key 等敏感配置仍只放在本地 `.env`。
- API 只返回密钥是否已配置的布尔状态，不返回真实密钥值。
- `POST /api/run-daily/async` 字段缺失时会使用 `workspace/ui_settings.json` 中的默认运行参数；未显式传入 `daily_keywords` 时会使用 UI 保存的关键词，若 UI 配置文件不存在则回退到 `.env` 的 `DAILY_KEYWORDS`。

## React Web 控制台

React 控制台位于 `frontend/`，默认连接本地 FastAPI：

```text
http://127.0.0.1:8000
```

如需调整后端地址，可复制前端环境变量示例：

```bash
cd frontend
cp .env.example .env
```

启动顺序：

```bash
# 1. 启动后端 API
python3 api_server.py

# 2. 另开终端启动前端
cd frontend
pnpm install
pnpm run dev
```

如果没有 `pnpm`，也可以使用 npm：

```bash
cd frontend
npm install
npm run dev
```

前端能力：

- React 控制台使用侧边栏多页面视图，不依赖 React Router，通过本地页面状态切换 Dashboard、Candidates、Score Ranking、Research Notes、Topic Angles、Articles、Reviews、Runs History 和 Settings。
- Dashboard 首屏从 `GET /api/dashboard` 读取真实运行数据；后端不可用时会显示 warning，并自动回退到 `mockData.ts` 示例数据，不会白屏。
- Candidates、Score Ranking、Research Notes、Topic Angles 和 Reviews 分别读取 `GET /api/snapshots/discovery`、`score`、`research`、`angles`、`reviews` 的真实快照数据。
- Articles 从 `GET /api/articles/final` 读取系统发现文章和手动指定文章，并通过 `source: "daily" | "custom"` 标记来源。点击文章后读取对应 Markdown，支持预览、复制、下载、打开 GitHub；可单篇或批量生成/重新生成发布包，并查看和下载 `packaged_article.md`。
- Reports 可按日期查看 `article_packages.md`，并单独浏览每篇 `packaged_article.md`，本地截图图片会通过后端安全资源接口加载。
- Runs History 读取 `GET /api/runs/latest` 和 `GET /api/runs`，展示最近运行、历史运行和阶段状态。
- Settings 读取 `GET /api/config/status` 和 `GET /api/settings`，可编辑默认运行参数、发现关键词和前端默认语言；页面不展示真实密钥值。
- 顶部状态显示 GitHub token、LLM 和最近运行状态，但不会显示真实 token。
- Run Daily 按钮会调用后台任务接口，实时显示 Pipeline Progress 和 Run Logs，完成后刷新 Dashboard。
- Quick Actions 支持打开终稿索引、查看评分报告和复制最新 Markdown。

## 已完成能力

- GitHub 项目发现
- 多维评分排序
- README / release / issue 调研
- 选题角度、标题候选、开头钩子和文章大纲生成
- 公众号文章初稿生成
- 编辑评审与终稿输出
- 发布清理、文章配图与公众号发布包
- `run-daily` 全流程编排
- 本地 `schedule` 定时入口
- FastAPI Web API
- React Web 控制台
- Markdown / JSON 运行产物沉淀
- 示例输出、教程技术映射和验收清单

## 后续规划

- 更稳定的趋势数据：加入 star 增长曲线、时间窗口对比和去重策略。
- 更严格的事实校验：引入更多来源交叉验证，减少 README 单一来源偏差。
- 更细的编辑标准：按不同公众号风格配置标题尺度、文章长度和栏目结构。
- 发布前人工工作台：未来可做前端或表格视图，但第一版不包含。
- 公众号 API 发布：作为后续扩展，当前版本不会自动发布。
- 任务部署：后续可接入 cron、云函数或队列系统；当前版本只提供本地 `schedule`。

## 最终验收

本项目第 9 步的验收清单见 [docs/ACCEPTANCE_CHECKLIST.md](docs/ACCEPTANCE_CHECKLIST.md)。验收重点包括：

- README 是否完整说明项目目标、能力边界、快速开始和运行方式。
- 示例输出是否可展示、可复盘。
- 教程技术映射是否清楚说明 ReAct / Plan-and-Solve / Reflection 如何落地。
- `.env` 和 README 是否没有真实 token。
- `run-daily` 是否能完整跑通并生成日报、评审报告和终稿索引。
