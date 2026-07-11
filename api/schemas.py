from __future__ import annotations

from typing import List, Literal, Optional, Set

from pydantic import BaseModel, Field
from pydantic import validator


MAX_REFERENCE_TEXT_LENGTH = 120_000


def normalize_keywords(value: Optional[List[str]], *, allow_empty: bool = False) -> Optional[List[str]]:
    if value is None:
        return None

    keywords: List[str] = []
    seen: Set[str] = set()
    for item in value:
        keyword = str(item).strip()
        if not keyword:
            continue
        if len(keyword) > 80:
            raise ValueError("Each keyword must be 1-80 characters.")
        normalized_key = keyword.casefold()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        keywords.append(keyword)

    if not keywords and not allow_empty:
        raise ValueError("At least one keyword is required.")
    if len(keywords) > 30:
        raise ValueError("At most 30 keywords are allowed.")
    return keywords


class RunDailyRequest(BaseModel):
    limit_per_keyword: Optional[int] = Field(default=None, ge=1, le=50)
    score_top: Optional[int] = Field(default=None, ge=1, le=100)
    research_top: Optional[int] = Field(default=None, ge=1, le=20)
    article_top: Optional[int] = Field(default=None, ge=1, le=20)
    review_threshold: Optional[float] = Field(default=None, ge=0, le=100)
    cooldown_days: Optional[int] = Field(default=None, ge=0, le=365)
    ignore_history: Optional[bool] = None
    allow_recent_fallback: Optional[bool] = None
    prefer_growth_projects: Optional[bool] = None
    daily_keywords: Optional[List[str]] = None

    @validator("daily_keywords")
    def validate_daily_keywords(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return normalize_keywords(value, allow_empty=True)


class CustomArticleRequest(BaseModel):
    repo_url: str = Field(..., min_length=1, max_length=300)
    direction: Optional[str] = Field(default=None, max_length=20_000)
    reference_texts: List[str] = Field(default_factory=list, max_items=5)
    reference_source_names: List[str] = Field(default_factory=list, max_items=5)

    @validator("repo_url")
    def validate_repo_url(cls, value: str) -> str:
        repo_url = value.strip()
        if not repo_url:
            raise ValueError("repo_url is required.")
        lowered = repo_url.lower()
        if "token=" in lowered or "access_token" in lowered or ".env" in lowered:
            raise ValueError("repo_url must not contain tokens or .env content.")
        return repo_url

    @validator("direction")
    def validate_direction(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()

    @validator("reference_texts")
    def validate_reference_texts(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        for text in value:
            content = str(text or "").strip()
            if not content:
                continue
            if len(content) > MAX_REFERENCE_TEXT_LENGTH:
                raise ValueError(f"Each reference text must be at most {MAX_REFERENCE_TEXT_LENGTH} characters.")
            lowered = content.lower()
            if "openai_api_key" in lowered or "github_personal_access_token" in lowered or "\n.env" in lowered:
                raise ValueError("reference_texts must not contain token or .env content.")
            cleaned.append(content)
        return cleaned

    @validator("reference_source_names")
    def validate_reference_source_names(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        for index, name in enumerate(value, start=1):
            source_name = str(name or "").strip()[:120]
            cleaned.append(source_name or f"reference_text_{index}")
        return cleaned


class PackageArticlesRequest(BaseModel):
    top: Optional[int] = Field(default=3, ge=1, le=50)
    safe_names: List[str] = Field(default_factory=list, max_items=50)
    full_names: List[str] = Field(default_factory=list, max_items=50)

    @validator("safe_names")
    def validate_safe_names(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen: Set[str] = set()
        for item in value:
            safe_name = str(item or "").strip()
            if not safe_name:
                continue
            if "/" in safe_name or "\\" in safe_name or ".." in safe_name:
                raise ValueError("safe_names must contain safe article names only.")
            if safe_name not in seen:
                seen.add(safe_name)
                cleaned.append(safe_name)
        return cleaned

    @validator("full_names")
    def validate_full_names(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen: Set[str] = set()
        for item in value:
            full_name = str(item or "").strip()
            if not full_name:
                continue
            if full_name.count("/") != 1 or "\\" in full_name or ".." in full_name:
                raise ValueError("full_names must be GitHub owner/repo names.")
            if full_name not in seen:
                seen.add(full_name)
                cleaned.append(full_name)
        return cleaned


class NewsCollectRequest(BaseModel):
    hours: int = Field(default=24, ge=1, le=336)
    limit: int = Field(default=100, ge=1, le=500)
    sources: List[str] = Field(default_factory=list, max_items=10)
    keywords: List[str] = Field(default_factory=list, max_items=30)
    include_fulltext: bool = False
    translate: bool = True
    translate_limit: int = Field(default=50, ge=0, le=500)

    @validator("sources")
    def validate_sources(cls, value: List[str]) -> List[str]:
        allowed = {"official", "official_rss", "rss", "hn", "hackernews", "hacker_news", "arxiv", "gdelt", "rsshub"}
        cleaned: List[str] = []
        seen: Set[str] = set()
        for item in value:
            source = str(item or "").strip().lower()
            if not source:
                continue
            if source not in allowed:
                raise ValueError(f"Unsupported news source: {source}")
            if source not in seen:
                seen.add(source)
                cleaned.append(source)
        return cleaned

    @validator("keywords")
    def validate_news_keywords(cls, value: List[str]) -> List[str]:
        return normalize_keywords(value, allow_empty=True) or []


class NewsScoreRequest(BaseModel):
    top: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=60, ge=0, le=100)


class NewsEventBuildRequest(BaseModel):
    top: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=60, ge=0, le=100)
    similarity_threshold: float = Field(default=0.55, ge=0.35, le=0.9)


class NewsDigestWriteRequest(BaseModel):
    top: int = Field(default=12, ge=1, le=50)
    date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class NewsDigestReviewRequest(BaseModel):
    threshold: float = Field(default=80, ge=0, le=100)
    polish: bool = True


class NewsSelectionRequest(BaseModel):
    news_ids: List[str] = Field(default_factory=list, min_items=1, max_items=5)
    primary_news_id: Optional[str] = None
    direction_text: Optional[str] = Field(default=None, max_length=20_000)

    @validator("news_ids")
    def validate_news_ids(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen: Set[str] = set()
        for item in value:
            news_id = str(item or "").strip()
            if not news_id:
                continue
            if "/" in news_id or "\\" in news_id or ".." in news_id:
                raise ValueError("news_ids must contain safe news ids only.")
            if len(news_id) > 128:
                raise ValueError("Each news_id must be at most 128 characters.")
            if news_id in seen:
                continue
            seen.add(news_id)
            cleaned.append(news_id)
        if not cleaned:
            raise ValueError("At least one news item is required.")
        if len(cleaned) > 5:
            raise ValueError("At most 5 news items can be selected.")
        return cleaned

    @validator("primary_news_id")
    def validate_primary_news_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        news_id = value.strip()
        if not news_id:
            return None
        if "/" in news_id or "\\" in news_id or ".." in news_id or len(news_id) > 128:
            raise ValueError("primary_news_id must be a safe news id.")
        return news_id

    @validator("direction_text")
    def validate_direction_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None


class NewsArticlePlanRequest(BaseModel):
    selection_id: Optional[str] = None
    use_latest: bool = True

    @validator("selection_id")
    def validate_selection_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        selection_id = value.strip()
        if not selection_id:
            return None
        if "/" in selection_id or "\\" in selection_id or ".." in selection_id or len(selection_id) > 160:
            raise ValueError("selection_id must be a safe id.")
        return selection_id


class UiRunDefaults(BaseModel):
    limit_per_keyword: int = Field(default=3, ge=1, le=50)
    score_top: int = Field(default=30, ge=1, le=100)
    research_top: int = Field(default=3, ge=1, le=20)
    article_top: int = Field(default=3, ge=1, le=20)
    review_threshold: float = Field(default=80, ge=0, le=100)
    cooldown_days: int = Field(default=30, ge=0, le=365)
    ignore_history: bool = False
    allow_recent_fallback: bool = False
    prefer_growth_projects: bool = True


class UiDiscoverySettings(BaseModel):
    daily_keywords: List[str] = Field(default_factory=list)

    @validator("daily_keywords")
    def validate_daily_keywords(cls, value: List[str]) -> List[str]:
        return normalize_keywords(value, allow_empty=False) or []


class UiFrontendSettings(BaseModel):
    default_language: Literal["zh", "en"] = "zh"


class UiSettings(BaseModel):
    run_defaults: UiRunDefaults = Field(default_factory=UiRunDefaults)
    discovery: UiDiscoverySettings
    frontend: UiFrontendSettings = Field(default_factory=UiFrontendSettings)
