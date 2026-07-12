# AI 新闻文章 CLI/API Mapping

## CLI

- `python3 main.py collect-news`：采集 AI 新闻。
- `python3 main.py score-news`：评分、分类和排序新闻。
- `python3 main.py build-news-events`：聚合同一事件的多条新闻。
- `python3 main.py fetch-news-detail`：抓取单条新闻详情。
- `python3 main.py select-news`：保存选中的新闻。
- `python3 main.py plan-news-article`：生成单篇新闻文章策划。
- `python3 main.py write-news-article`：写作单篇 AI 新闻公众号文章。
- `python3 main.py review-news-article`：评估单篇 AI 新闻文章。
- `python3 main.py write-news-digest`：生成 AI 新闻日报。
- `python3 main.py review-news-digest`：评估 AI 新闻日报。

## API

- `GET /api/news/latest`：读取最新新闻列表。
- `POST /api/news/collect`：触发新闻采集。
- `GET /api/news/scores`：读取新闻评分结果。
- `POST /api/news/score`：触发新闻评分。
- `GET /api/news/events`：读取新闻事件聚合结果。
- `POST /api/news/events/build`：触发新闻事件聚合。
- `GET /api/news/items/{news_id}`：读取新闻详情。
- `POST /api/news/items/{news_id}/refresh`：刷新新闻详情。
- `POST /api/news/selections`：保存新闻选题。
- `GET /api/news/selections/latest`：读取最新新闻选题。
- `POST /api/news/article-plan`：生成单篇新闻文章策划。
- `GET /api/news/article-plan/latest`：读取最新文章策划。
- `POST /api/news/article/write`：写作单篇新闻文章。
- `GET /api/news/article/latest`：读取最新新闻文章。
- `POST /api/news/article/review`：评估最新新闻文章。
- `GET /api/news/article/latest/publish`：读取最新新闻文章发布形态。
- `GET /api/news/digest`：读取 AI 新闻日报。
- `POST /api/news/digest/write`：生成 AI 新闻日报。
- `POST /api/news/digest/review`：评估 AI 新闻日报。
