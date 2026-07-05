from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RepoCandidate(BaseModel):
    name: str
    full_name: str
    owner: str
    html_url: str
    description: Optional[str] = None
    stars: int = 0
    stargazers_count: Optional[int] = None
    watchers_count: Optional[int] = None
    forks: int = 0
    open_issues: Optional[int] = None
    language: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pushed_at: Optional[str] = None
    default_branch: Optional[str] = None
    license_name: Optional[str] = None
    url: Optional[str] = None
    homepage: Optional[str] = None
    discovery_reason: Optional[str] = None


class AuthorProfile(BaseModel):
    login: str
    type: Optional[str] = None
    name: Optional[str] = None
    html_url: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    company: Optional[str] = None
    blog: Optional[str] = None
    location: Optional[str] = None
    twitter_username: Optional[str] = None
    public_repos: Optional[int] = None
    followers: Optional[int] = None
    created_at: Optional[str] = None
    source: str = "github_users_api"


class ProjectLinks(BaseModel):
    homepage: Optional[str] = None
    documentation: List[str] = Field(default_factory=list)
    demo: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    website: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    videos: List[str] = Field(default_factory=list)
    badges: List[str] = Field(default_factory=list)


class RepoScore(BaseModel):
    full_name: str
    html_url: str
    total_score: float = 0.0
    growth_score: float = 0.0
    velocity_score: float = 0.0
    freshness_score: float = 0.0
    relevance_score: float = 0.0
    quality_score: float = 0.0
    activity_score: float = 0.0
    communication_score: float = 0.0
    discovery_reason: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class RepoResearchNote(BaseModel):
    full_name: str
    html_url: str
    description: Optional[str] = None
    stars: int = 0
    forks: int = 0
    language: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    license_name: Optional[str] = None
    pushed_at: Optional[str] = None
    readme_summary: str = ""
    readme_key_points: List[str] = Field(default_factory=list)
    releases: List[dict] = Field(default_factory=list)
    open_issues: List[dict] = Field(default_factory=list)
    source_links: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    author_profile: Optional[AuthorProfile] = None
    project_links: Optional[ProjectLinks] = None
    readme_images: List[str] = Field(default_factory=list)
    readme_links: List[str] = Field(default_factory=list)
    tool_use_cases: List[str] = Field(default_factory=list)
    project_kind: Optional[str] = None


class TitleCandidate(BaseModel):
    title: str
    style: str
    reason: str
    risk: Optional[str] = None


class TopicAngle(BaseModel):
    full_name: str
    html_url: str
    project_name: str
    selected_angle: str
    one_liner: str
    target_readers: List[str] = Field(default_factory=list)
    reader_pain_points: List[str] = Field(default_factory=list)
    selling_points: List[str] = Field(default_factory=list)
    title_candidates: List[TitleCandidate] = Field(default_factory=list)
    opening_hook: str
    article_outline: List[str] = Field(default_factory=list)
    cover_prompt: str
    source_links: List[str] = Field(default_factory=list)
    factual_warnings: List[str] = Field(default_factory=list)


class FactCard(BaseModel):
    full_name: str
    claim: str
    category: str
    source: str
    source_type: str
    confidence: str
    publishable: bool
    note: Optional[str] = None


class ProjectInsight(BaseModel):
    full_name: str
    project_name: str
    plain_summary: str
    problem_solved: str
    core_value: str
    ideal_users: List[str] = Field(default_factory=list)
    use_cases: List[str] = Field(default_factory=list)
    standout_points: List[str] = Field(default_factory=list)
    adoption_notes: List[str] = Field(default_factory=list)
    local_context: str
    not_to_overclaim: List[str] = Field(default_factory=list)
    source_fact_ids: List[int] = Field(default_factory=list)


class NarrativeStrategy(BaseModel):
    pattern: str
    rationale: str
    opening_style: str
    structure_style: str
    title_style: str
    avoid_patterns: List[str] = Field(default_factory=list)
    transition_notes: List[str] = Field(default_factory=list)


class TitleStrategy(BaseModel):
    directions: List[str] = Field(default_factory=list)
    banned_templates: List[str] = Field(default_factory=list)
    title_candidates: List[TitleCandidate] = Field(default_factory=list)
    rationale: str = ""


class WriterPersona(BaseModel):
    persona: str = "programmer"
    voice: str = "像一个经常折腾开发工具的程序员"
    article_goal: str = "激发读者兴趣"
    do: List[str] = Field(default_factory=list)
    dont: List[str] = Field(default_factory=list)


class CustomArticleDirection(BaseModel):
    raw_text: str = ""
    target_reader: Optional[str] = None
    writing_perspective: Optional[str] = None
    core_angle: Optional[str] = None
    must_include: List[str] = Field(default_factory=list)
    avoid_topics: List[str] = Field(default_factory=list)
    tone_preferences: List[str] = Field(default_factory=list)
    title_preferences: List[str] = Field(default_factory=list)
    content_preferences: List[str] = Field(default_factory=list)


class StyleReferenceProfile(BaseModel):
    raw_count: int = 0
    source_names: List[str] = Field(default_factory=list)
    tone_traits: List[str] = Field(default_factory=list)
    pacing_traits: List[str] = Field(default_factory=list)
    opening_patterns: List[str] = Field(default_factory=list)
    transition_patterns: List[str] = Field(default_factory=list)
    title_patterns: List[str] = Field(default_factory=list)
    sentence_style: List[str] = Field(default_factory=list)
    reader_relationship: Optional[str] = None
    structure_tendencies: List[str] = Field(default_factory=list)
    do_not_copy: List[str] = Field(default_factory=list)
    originality_rules: List[str] = Field(default_factory=list)
    summary: str = ""


class EditorialBrief(BaseModel):
    full_name: str
    recommended_angle: str
    narrative_pattern: str
    target_reader: str
    reader_takeaway: str
    title_direction: List[str] = Field(default_factory=list)
    opening_direction: str
    must_include: List[str] = Field(default_factory=list)
    should_avoid: List[str] = Field(default_factory=list)
    suggested_structure: List[str] = Field(default_factory=list)
    tone: str
    visual_needs: List[str] = Field(default_factory=list)
    narrative_strategy: Optional[NarrativeStrategy] = None
    title_strategy: Optional[TitleStrategy] = None
    article_differentiators: List[str] = Field(default_factory=list)
    human_tone_rules: List[str] = Field(default_factory=list)
    paragraph_plan: List[str] = Field(default_factory=list)
    writer_persona: Optional[WriterPersona] = None


class FeatureAdvantage(BaseModel):
    feature: str = ""
    advantage: str = ""
    reader_interest: str = ""
    evidence: str = ""
    emphasis: str = "medium"


class ProjectAppeal(BaseModel):
    full_name: str = ""
    project_name: str = ""
    appeal_summary: str = ""
    primary_hook: str = ""
    feature_advantages: List[FeatureAdvantage] = Field(default_factory=list)
    top_selling_points: List[str] = Field(default_factory=list)
    reader_interest_points: List[str] = Field(default_factory=list)
    practical_scenarios: List[str] = Field(default_factory=list)
    differentiation_points: List[str] = Field(default_factory=list)
    avoid_overemphasis: List[str] = Field(default_factory=list)
    recommended_focus: List[str] = Field(default_factory=list)
    confidence: str = "medium"


class ProjectImpact(BaseModel):
    full_name: str = ""
    core_effect: str = ""
    effect_summary: str = ""
    concrete_outcomes: List[str] = Field(default_factory=list)
    before_after_examples: List[str] = Field(default_factory=list)
    usage_examples: List[str] = Field(default_factory=list)
    user_benefits: List[str] = Field(default_factory=list)
    measurable_signals: List[str] = Field(default_factory=list)
    article_expansion_points: List[str] = Field(default_factory=list)
    weak_or_unknown_effects: List[str] = Field(default_factory=list)


class WechatArticlePattern(BaseModel):
    pattern_type: str = "practical_tool"
    opening_strategy: str = "pain_hook"
    title_formula: str = "这个开源项目，把 XXX 做得很顺手"
    lead_hook: str = "先从一个具体麻烦切入，再自然带出项目为什么值得看。"
    key_storyline: str = "痛点 -> 项目怎么解决 -> 具体效果 -> 适合谁继续点开"
    required_effect_points: List[str] = Field(default_factory=list)
    required_examples: List[str] = Field(default_factory=list)
    allowed_colloquial_phrases: List[str] = Field(
        default_factory=lambda: [
            "这个点挺实用",
            "用过一次就很难回去",
            "单拎出来都值得试试",
            "适合花一个下午玩玩",
            "有点东西",
        ]
    )
    banned_phrases: List[str] = Field(
        default_factory=lambda: [
            "发现一个 XX star 项目",
            "根据 README",
            "资料显示",
            "数据可能变化",
            "本文将从以下几个方面",
            "综上",
            "值得关注",
            "具有较高参考价值",
            "建议结合实际情况",
        ]
    )
    image_placement_hints: List[str] = Field(
        default_factory=lambda: [
            "开头后放项目总览截图",
            "demo 场景后放对应截图",
            "功能点后放 README 图片",
            "README 无图时使用 GitHub README 页面截图",
        ]
    )
    ending_style: str = "自然收束到适合谁试试，文末只保留项目地址。"


class ArticleDraft(BaseModel):
    full_name: str = ""
    html_url: str = ""
    title: str
    title_candidates: List[TitleCandidate] = Field(default_factory=list)
    summary: str = ""
    content_markdown: str = ""
    cover_prompt: str = ""
    source_links: List[str] = Field(default_factory=list)
    factual_warnings: List[str] = Field(default_factory=list)
    word_count: int = 0
    generation_mode: str = "fallback"
    content_plan_used: bool = False
    narrative_pattern: Optional[str] = None
    title_style: Optional[str] = None
    article_style_notes: List[str] = Field(default_factory=list)
    source_fact_ids: List[int] = Field(default_factory=list)
    writer_persona: Optional[WriterPersona] = None
    top_selling_points_used: List[str] = Field(default_factory=list)
    practical_scenarios_used: List[str] = Field(default_factory=list)
    repo_full_name: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ArticleReview(BaseModel):
    full_name: str
    title: str
    total_score: float
    factual_score: float
    title_score: float
    structure_score: float
    readability_score: float
    completeness_score: float
    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    revision_suggestions: List[str] = Field(default_factory=list)
    pass_review: bool
    review_mode: str = "fallback"


class HumanizationIssue(BaseModel):
    category: str
    severity: str
    text: str
    suggestion: str


class HumanizationReport(BaseModel):
    full_name: str
    ai_smell_score: float = 100.0
    readme_similarity_risk: float = 0.0
    template_risk: float = 0.0
    localization_score: float = 100.0
    issues: List[HumanizationIssue] = Field(default_factory=list)
    rewrite_suggestions: List[str] = Field(default_factory=list)
    pass_humanization: bool = True
    mode: str = "heuristic"


class PublishPolishReport(BaseModel):
    full_name: str
    publish_ready: bool
    mode: str = "heuristic"
    removed_sections: List[str] = Field(default_factory=list)
    removed_phrases: List[str] = Field(default_factory=list)
    kept_links: List[str] = Field(default_factory=list)
    remaining_issues: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    direction_followed: bool = True
    violated_preferences: List[str] = Field(default_factory=list)


class OriginalityIssue(BaseModel):
    issue_type: str = ""
    severity: str = "low"
    description: str = ""
    matched_text: Optional[str] = None
    recommendation: str = ""


class OriginalityReport(BaseModel):
    checked: bool = False
    passed: bool = True
    similarity_score: float = 0.0
    max_common_sequence_length: int = 0
    copied_sentence_count: int = 0
    structure_similarity: float = 0.0
    issues: List[OriginalityIssue] = Field(default_factory=list)
    rewrite_attempted: bool = False
    rewrite_mode: str = "none"
    summary: str = ""


class ArticleQualityIssue(BaseModel):
    issue_type: str = ""
    severity: str = "low"
    description: str = ""
    suggestion: str = ""
    evidence: Optional[str] = None


class ArticleQualityReport(BaseModel):
    full_name: str = ""
    title: str = ""
    total_score: float = 0.0
    publish_ready: bool = False
    title_score: float = 0.0
    opening_score: float = 0.0
    project_value_score: float = 0.0
    concrete_example_score: float = 0.0
    effect_depth_score: float = 0.0
    readability_score: float = 0.0
    human_tone_score: float = 0.0
    anti_readme_score: float = 0.0
    wechat_style_score: float = 0.0
    issues: List[ArticleQualityIssue] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    rewrite_recommendations: List[str] = Field(default_factory=list)
    summary: str = ""


class FinalArticle(BaseModel):
    full_name: str
    html_url: str
    title: str
    summary: str
    content_markdown: str
    cover_prompt: str
    source_links: List[str] = Field(default_factory=list)
    factual_warnings: List[str] = Field(default_factory=list)
    review: ArticleReview
    revision_mode: str = "unchanged"
    word_count: int = 0
    generation_mode: str = "fallback"
    content_plan_used: bool = False
    narrative_pattern: Optional[str] = None
    title_style: Optional[str] = None
    article_style_notes: List[str] = Field(default_factory=list)
    source_fact_ids: List[int] = Field(default_factory=list)
    writer_persona: Optional[WriterPersona] = None
    top_selling_points_used: List[str] = Field(default_factory=list)
    practical_scenarios_used: List[str] = Field(default_factory=list)
    humanization_report: Optional[HumanizationReport] = None
    humanization_mode: Optional[str] = None
    humanized: bool = False
    publish_polish_report: Optional[PublishPolishReport] = None
    publish_ready: bool = False
    publish_polish_mode: Optional[str] = None
    originality_report: Optional[OriginalityReport] = None
    originality_checked: bool = False
    originality_passed: bool = True
    article_quality_report: Optional[ArticleQualityReport] = None
    quality_score: float = 0.0
    quality_publish_ready: bool = False


class VisualAsset(BaseModel):
    full_name: str
    asset_id: str = ""
    asset_type: str = ""
    title: str = ""
    description: str = ""
    source_url: Optional[str] = None
    output_path: Optional[str] = None
    format: str = "png"
    status: str = "planned"
    error: Optional[str] = None


class ArticlePackage(BaseModel):
    full_name: str
    title: str
    article_path: str
    packaged_article_path: str
    assets: List[VisualAsset] = Field(default_factory=list)
    cover_prompt: str = ""
    package_dir: str
    status: str = "planned"
    notes: List[str] = Field(default_factory=list)


class DailyRun(BaseModel):
    run_id: str
    date: str
    started_at: str
    finished_at: Optional[str] = None
    status: str = "running"
    current_stage: Optional[str] = None
    stages: List[dict] = Field(default_factory=list)
    output_dir: str
    snapshot_files: List[str] = Field(default_factory=list)
    final_article_files: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    selection_summary: Optional[dict] = None
