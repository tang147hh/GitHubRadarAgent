from __future__ import annotations

import re


INTERACTION_METRIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"点赞"),
    re.compile(r"评论数"),
    re.compile(r"\bpoints\b", re.IGNORECASE),
    re.compile(r"\bcomments\b", re.IGNORECASE),
    re.compile(r"评论区炸了"),
    re.compile(r"评论区"),
    re.compile(r"很多人讨论"),
    re.compile(r"大家都在讨论"),
    re.compile(r"开发者普遍认为"),
    re.compile(r"讨论量很大"),
    re.compile(r"讨论热度"),
    re.compile(r"热度很高"),
    re.compile(r"社区讨论很多"),
    re.compile(r"评论很多"),
    re.compile(r"点赞很多"),
)

UNSUPPORTED_COMMUNITY_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"开发者普遍认为"),
    re.compile(r"社区普遍认为"),
    re.compile(r"网友普遍认为"),
    re.compile(r"社区观点"),
    re.compile(r"大家都认为"),
)


def interaction_metric_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in INTERACTION_METRIC_PATTERNS:
        match = pattern.search(text or "")
        if match:
            value = match.group(0)
            if value not in hits:
                hits.append(value)
    return hits


def unsupported_community_claim_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in UNSUPPORTED_COMMUNITY_CLAIM_PATTERNS:
        match = pattern.search(text or "")
        if match:
            value = match.group(0)
            if value not in hits:
                hits.append(value)
    return hits


def contains_interaction_metric(text: str) -> bool:
    return bool(interaction_metric_hits(text))


def without_interaction_metric_values(values: list[str]) -> list[str]:
    return [value for value in values if not contains_interaction_metric(str(value or ""))]


def strip_interaction_metric_text(markdown: str) -> str:
    """Remove interaction-metric language while trying to preserve factual text and URLs."""
    content = markdown or ""
    replacements = {
        "HN 上很多人讨论这个问题": "这条消息来自 Hacker News",
        "Hacker News 上很多人讨论这个问题": "这条消息来自 Hacker News",
        "这条新闻评论很多，说明大家很关注": "",
        "评论区炸了": "",
        "大家都在讨论": "",
        "很多人讨论": "",
        "开发者普遍认为": "",
        "讨论量很大": "",
        "讨论热度": "来源线索",
        "热度很高": "",
        "社区讨论很多": "",
        "评论很多": "",
        "点赞很多": "",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    sentence_split = re.compile(r"([^。！？!?]*[。！？!?]?)")
    cleaned_lines: list[str] = []
    for line in content.splitlines():
        if not contains_interaction_metric(line):
            cleaned_lines.append(line)
            continue
        if re.search(r"https?://", line):
            cleaned_lines.append(_remove_metric_fragments(line))
            continue
        pieces = [piece for piece in sentence_split.findall(line) if piece]
        kept = [_remove_metric_fragments(piece) for piece in pieces if not _sentence_depends_on_metric(piece)]
        cleaned = "".join(piece for piece in kept if piece.strip())
        if cleaned.strip():
            cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines)


def _sentence_depends_on_metric(sentence: str) -> bool:
    if not contains_interaction_metric(sentence):
        return False
    factual_markers = ["发布", "推出", "宣布", "开源", "论文", "模型", "API", "监管", "原文链接", "Hacker News", "HN"]
    return not any(marker in sentence for marker in factual_markers)


def _remove_metric_fragments(text: str) -> str:
    cleaned = text
    fragment_patterns = (
        r"[，,。；;]?\s*评论数[^，,。；;\n]*",
        r"[，,。；;]?\s*点赞数[^，,。；;\n]*",
        r"[，,。；;]?\s*\bpoints\b[^，,。；;\n]*",
        r"[，,。；;]?\s*\bcomments\b[^，,。；;\n]*",
        r"[，,。；;]?\s*评论区[^，,。；;\n]*",
        r"[，,。；;]?\s*很多人讨论[^，,。；;\n]*",
        r"[，,。；;]?\s*大家都在讨论[^，,。；;\n]*",
        r"[，,。；;]?\s*讨论量很大[^，,。；;\n]*",
        r"[，,。；;]?\s*热度很高[^，,。；;\n]*",
        r"[，,。；;]?\s*社区讨论很多[^，,。；;\n]*",
        r"[，,。；;]?\s*评论很多[^，,。；;\n]*",
        r"[，,。；;]?\s*点赞很多[^，,。；;\n]*",
    )
    for pattern in fragment_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip()
