from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SourceType = Literal["official_rss", "rsshub", "hackernews", "arxiv", "gdelt", "webpage"]


@dataclass(frozen=True)
class RssSource:
    name: str
    url: str
    source_type: SourceType = "official_rss"
    topics: tuple[str, ...] = ("ai",)
    enabled: bool = True
    note: str = ""


DEFAULT_RSS_SOURCES: list[RssSource] = [
    RssSource("OpenAI News", "https://openai.com/news/rss.xml", topics=("ai", "company", "model")),
    RssSource("Anthropic News", "https://www.anthropic.com/news/rss.xml", topics=("ai", "company", "model")),
    RssSource("Google DeepMind Blog", "https://deepmind.google/blog/rss.xml", topics=("ai", "research")),
    RssSource("Google Research Blog", "https://research.google/blog/rss/", topics=("ai", "research")),
    RssSource("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", topics=("ai", "open-source")),
    RssSource("GitHub Blog", "https://github.blog/feed/", topics=("developer-tools", "ai")),
    RssSource("LangChain Blog", "https://blog.langchain.com/rss/", topics=("agent", "llm")),
    RssSource(
        "Cursor Blog",
        "https://www.cursor.com/blog/rss.xml",
        topics=("developer-tools", "ai"),
        note="Cursor RSS is best-effort; if unavailable the collector records a warning.",
    ),
]


RSSHUB_ROUTES: list[RssSource] = [
    RssSource("RSSHub GitHub Blog", "/github/blog", source_type="rsshub", topics=("developer-tools", "ai")),
]


DEFAULT_NEWS_KEYWORDS: list[str] = [
    "OpenAI",
    "Anthropic",
    "DeepSeek",
    "LLM",
    "AI agent",
    "AI regulation",
    "NVIDIA AI",
]


SOURCE_ALIASES: dict[str, str] = {
    "official": "official",
    "official_rss": "official",
    "rss": "official",
    "hn": "hn",
    "hackernews": "hn",
    "hacker_news": "hn",
    "arxiv": "arxiv",
    "gdelt": "gdelt",
    "rsshub": "rsshub",
}


DEFAULT_SOURCE_GROUPS: list[str] = ["official", "hn", "arxiv", "gdelt"]
