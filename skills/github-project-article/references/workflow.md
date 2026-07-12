# GitHub 项目文章 Workflow

## 自动发现项目写作流程

1. `discover`：从 GitHub 发现候选仓库，形成候选项目列表。
2. `score`：按项目吸引力、可写性、热度、差异化等维度评分。
3. `select-projects`：选择适合当天写作的项目，避免与历史文章重复。
4. `research-selected`：研究选中项目的 README、代码结构、示例、截图和项目定位。
5. `angles`：生成面向公众号读者的选题角度。
6. `plan-content`：规划文章结构、标题方向、重点段落和素材使用方式。
7. `write-articles`：生成 Markdown 文章。
8. `review-articles`：检查质量、表达、事实边界和发布可读性。
9. `package-articles`：生成发布包和图片资源，确保公众号发布形态完整。

## 指定 GitHub 链接写作流程

1. `parse repo URL`：解析用户给出的 GitHub 仓库地址，提取 owner、repo 和可访问链接。
2. `research single repo`：研究单个仓库的 README、描述、主题、示例、图片和核心能力。
3. `parse user direction`：解析用户额外要求，例如目标读者、文章风格、标题方向、是否偏教程。
4. `analyze style reference if provided`：如用户提供参考文风，先抽取表达节奏、段落长度和叙述方式。
5. `plan content`：规划文章主线，避免照搬 README 顺序。
6. `write article`：生成原创公众号文章，突出项目解决什么问题、怎么用、适合谁。
7. `review/humanize/publish polish`：检查机械感、口水话、禁用表达和公众号发布可读性。
8. `originality guard if reference provided`：如果有参考文章，检查相似表达，避免近似改写。
9. `quality evaluate`：评估标题、事实、结构、例子、配图和发布边界。
10. `package article`：生成发布包，补齐图片、Markdown 和可交付路径。

## 异常处理

- GitHub API rate limit：降低请求频率，优先使用已有缓存或本地快照；必要时提示用户稍后重试或配置 token。
- README 拉取失败：尝试 GitHub 页面、默认分支、仓库描述和文件树；仍失败时换项目或要求用户补充信息。
- LLM 不可用：保留已完成的发现、评分、研究结果；提示缺少写作或评估产物，等待模型恢复后继续。
- 无合适图片：优先纯文字发布；不要强行生成与项目无关的装饰图。
- 质量分低：定位问题是 README 感、事实不足、标题弱、例子少还是发布格式差，再重写对应环节。

## Agent 自主判断

- 候选项目重复时，扩大 `score_top` 或增加 `cooldown_days`，直到出现足够新鲜的候选。
- 项目资料不足、定位不清或无法形成具体使用场景时，主动换项目。
- 文章像 README 摘要时，回到策划阶段重写主线，改成用户问题、效果和例子驱动。
- 缺少发布包时，补跑 `package-articles`，不要只交付裸 Markdown。
