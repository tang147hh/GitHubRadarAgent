from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


SourceType = Literal["official_rss", "rsshub", "hackernews", "community_discussion", "arxiv", "gdelt", "webpage"]
SourceCategory = Literal[
    "official_product",
    "policy_regulation",
    "trend_industry",
    "research_breakthrough",
    "fun_story",
    "developer_community",
    "noise",
]


@dataclass(frozen=True)
class RssSource:
    name: str
    url: str
    source_type: SourceType = "official_rss"
    source_category: SourceCategory = "official_product"
    topics: tuple[str, ...] = ("ai",)
    priority_weight: float = 1.0
    enabled: bool = True
    note: str = ""


DEFAULT_RSS_SOURCES: list[RssSource] = [
    RssSource("OpenAI News", "https://openai.com/news/rss.xml", topics=("ai", "company", "model"), priority_weight=1.35),
    RssSource("Anthropic News", "", enabled=False, note="The previously configured RSS endpoint returned 404; awaiting a stable official feed."),
    RssSource("Google DeepMind Blog", "https://deepmind.google/blog/rss.xml", topics=("ai", "research"), priority_weight=1.3),
    RssSource("Google Research Blog", "https://research.google/blog/rss/", source_category="research_breakthrough", topics=("ai", "research"), priority_weight=1.25),
    RssSource("Microsoft AI Blog", "", enabled=False, note="The previously configured RSS endpoint returned 410; awaiting a stable official feed."),
    RssSource("NVIDIA AI Blog", "https://blogs.nvidia.com/blog/category/deep-learning/feed/", topics=("ai", "infrastructure", "chip"), priority_weight=1.25),
    RssSource("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", topics=("ai", "open-source"), priority_weight=1.15),
    RssSource("MIT News AI", "https://news.mit.edu/rss/topic/artificial-intelligence2", source_category="research_breakthrough", topics=("ai", "research", "impact"), priority_weight=1.25),
    RssSource("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", source_category="trend_industry", topics=("ai", "industry", "business"), priority_weight=1.15),
    RssSource("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", source_category="trend_industry", topics=("ai", "startup", "business"), priority_weight=1.15),
    RssSource("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", source_category="trend_industry", topics=("ai", "product", "society"), priority_weight=1.1),
    RssSource("WIRED AI", "https://www.wired.com/feed/tag/ai/latest/rss", source_category="trend_industry", topics=("ai", "society", "policy"), priority_weight=1.1),
    RssSource("The Decoder", "https://the-decoder.com/feed/", source_category="trend_industry", topics=("ai", "industry", "research"), priority_weight=1.1),
    RssSource("GitHub Blog", "https://github.blog/feed/", source_category="developer_community", topics=("developer-tools", "ai"), priority_weight=0.65),
    RssSource("LangChain Blog", "https://blog.langchain.com/rss/", source_category="developer_community", topics=("agent", "llm"), priority_weight=0.6),
    RssSource("Cursor Blog", "", source_category="developer_community", enabled=False, note="The previously configured RSS endpoint returned 404; awaiting a stable feed."),
    # Kept as configuration placeholders until a stable public feed is confirmed.
    RssSource("Meta AI", "", enabled=False, note="No stable public RSS endpoint configured."),
    RssSource("Stanford HAI", "", source_category="research_breakthrough", enabled=False, note="No stable public RSS endpoint configured."),
    RssSource("OECD.AI", "", source_category="policy_regulation", enabled=False, note="Collected through policy keyword search until a stable feed is configured."),
    RssSource("EU AI Act", "", source_category="policy_regulation", enabled=False, note="Collected through policy keyword search until a stable feed is configured."),
    RssSource("NIST AI", "", source_category="policy_regulation", enabled=False, note="Collected through policy keyword search until a stable feed is configured."),
]


RSSHUB_ROUTES: list[RssSource] = [
    RssSource("RSSHub GitHub Blog", "/github/blog", source_type="rsshub", source_category="developer_community", topics=("developer-tools", "ai"), priority_weight=0.55),
]


POLICY_KEYWORDS = [
    "AI regulation", "AI policy", "AI Act", "copyright", "lawsuit", "safety", "governance",
    "national security", "data privacy", "model risk", "government", "regulator", "compliance",
    "监管", "政策", "版权", "诉讼", "安全", "治理", "合规",
]
TREND_KEYWORDS = [
    "AI agent", "AI browser", "AI coding", "enterprise AI", "AI infrastructure", "inference", "robotics",
    "AI chip", "model adoption", "automation", "copilots", "AI search", "AI video", "multimodal",
    "趋势", "产业", "商业化", "落地", "智能体", "AI 编程", "AI 浏览器", "AI 搜索", "AI 视频", "多模态", "推理成本",
]
FUN_STORY_KEYWORDS = [
    "weird", "funny", "viral", "surprising", "accidentally", "strange", "experiment", "story",
    "case study", "bizarre", "unexpected", "趣事", "翻车", "意外", "爆火", "离谱", "有意思",
]
INDUSTRY_KEYWORDS = [
    "funding", "acquisition", "partnership", "launch", "revenue", "customers", "enterprise", "platform",
    "startup", "market", "融资", "收购", "产业", "商业化", "落地",
]
RESEARCH_KEYWORDS = ["research", "paper", "benchmark", "breakthrough", "arXiv", "论文", "研究", "突破"]

EDITORIAL_KEYWORDS = {
    "policy_regulation": POLICY_KEYWORDS,
    "trend_industry": TREND_KEYWORDS,
    "fun_story": FUN_STORY_KEYWORDS,
    "industry": INDUSTRY_KEYWORDS,
    "research_breakthrough": RESEARCH_KEYWORDS,
}

DEFAULT_NEWS_KEYWORDS: list[str] = [
    "AI regulation", "AI policy", "copyright", "AI agent", "enterprise AI", "AI infrastructure",
    "AI chip", "AI search", "AI video", "multimodal", "funding", "acquisition", "OpenAI", "Anthropic",
    "Google DeepMind", "NVIDIA AI", "监管", "政策", "版权", "融资", "收购", "智能体", "AI 编程",
]

SOURCE_ALIASES: dict[str, str] = {
    "official": "official", "official_rss": "official", "rss": "official", "hn": "hn",
    "hackernews": "hn", "hacker_news": "hn", "arxiv": "arxiv", "gdelt": "gdelt", "rsshub": "rsshub",
}

# HN remains enabled for backwards-compatible commands, but is ranked as a supplemental pool.
DEFAULT_SOURCE_GROUPS: list[str] = ["official", "gdelt", "arxiv", "hn"]


SOURCE_CATEGORY_WEIGHTS: dict[str, float] = {
    "official_product": 1.35,
    "policy_regulation": 1.35,
    "trend_industry": 1.2,
    "research_breakthrough": 1.2,
    "fun_story": 1.05,
    "developer_community": 0.45,
    "noise": 0.1,
}


def infer_editorial_category(text: str, fallback: str = "trend_industry") -> str:
    lowered = (text or "").casefold()

    def contains(keyword: str) -> bool:
        needle = keyword.casefold()
        if all(character.isascii() for character in needle):
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered))
        return needle in lowered

    matches = {
        category: sum(1 for keyword in keywords if contains(keyword))
        for category, keywords in EDITORIAL_KEYWORDS.items()
    }
    if matches["policy_regulation"]:
        return "policy_regulation"
    strong_fun_keywords = [keyword for keyword in FUN_STORY_KEYWORDS if keyword not in {"experiment", "story", "case study"}]
    if any(contains(keyword) for keyword in strong_fun_keywords):
        return "fun_story"
    if matches["research_breakthrough"] and matches["research_breakthrough"] >= matches["trend_industry"]:
        return "research_breakthrough"
    if matches["industry"] or matches["trend_industry"]:
        return "trend_industry"
    return fallback
