export type DashboardStats = {
  today_candidates?: number;
  top_scored_projects?: number;
  final_articles?: number;
  review_pass_rate?: string | number;
  average_quality_score?: number;
};

export type DashboardHealth = {
  github_token_configured?: boolean;
  llm_configured?: boolean;
  last_run_status?: string;
};

export type RunInfo = {
  run_id?: string | null;
  status?: string | null;
  duration?: string | null;
  output?: string | null;
};

export type PipelineStage = {
  name?: string;
  status?: string;
  message?: string;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type ScoreRankingItem = {
  rank?: number;
  full_name?: string;
  project?: string;
  html_url?: string;
  stars?: number | string;
  stargazers_count?: number;
  score?: number;
  total_score?: number;
  growth_score?: number;
  velocity_score?: number;
  freshness_score?: number;
  relevance_score?: number;
  quality_score?: number;
  activity_score?: number;
  communication_score?: number;
  discovery_reason?: string | null;
  reasons?: string[];
  warnings?: string[];
  language?: string;
  status?: string;
};

export type FinalArticleItem = {
  title?: string;
  full_name?: string;
  repo_full_name?: string;
  project?: string;
  safe_name?: string;
  source?: "daily" | "custom" | string;
  summary?: string;
  word_count?: number;
  words?: number;
  review_score?: number;
  reviewScore?: number;
  pass_review?: boolean;
  html_url?: string;
  local_markdown_path?: string | null;
  generation_mode?: string;
  content_plan_used?: boolean;
  narrative_pattern?: string | null;
  title_style?: string | null;
  humanized?: boolean;
  humanization_mode?: string | null;
  ai_smell_score?: number | null;
  template_risk?: number | null;
  localization_score?: number | null;
  readme_similarity_risk?: number | null;
  publish_ready?: boolean;
  publish_polish_mode?: string | null;
  article_quality_report?: ArticleQualityReport | null;
  quality_score?: number | null;
  quality_publish_ready?: boolean;
  packaged_article_path?: string | null;
  package_path?: string | null;
  packaged_article_available?: boolean;
  markdown_path?: string | null;
  generated_at?: string;
  selected_readme_images?: string[];
  asset_count?: number;
};

export type ArticleQualityIssue = {
  issue_type?: string;
  severity?: "low" | "medium" | "high" | string;
  description?: string;
  suggestion?: string;
  evidence?: string | null;
};

export type ArticleQualityReport = {
  full_name?: string;
  title?: string;
  total_score?: number;
  publish_ready?: boolean;
  title_score?: number;
  opening_score?: number;
  project_value_score?: number;
  concrete_example_score?: number;
  effect_depth_score?: number;
  readability_score?: number;
  human_tone_score?: number;
  anti_readme_score?: number;
  wechat_style_score?: number;
  issues?: ArticleQualityIssue[];
  strengths?: string[];
  rewrite_recommendations?: string[];
  summary?: string;
};

export type ArticleQualitySnapshot = {
  generated_at?: string;
  total_count?: number;
  average_score?: number;
  publish_ready_count?: number;
  low_quality_count?: number;
  reports?: ArticleQualityReport[];
  warnings?: string[];
};

export type HumanizationIssue = {
  category?: string;
  severity?: string;
  text?: string;
  suggestion?: string;
};

export type HumanizationReportItem = {
  full_name?: string;
  ai_smell_score?: number;
  readme_similarity_risk?: number;
  template_risk?: number;
  localization_score?: number;
  issues?: HumanizationIssue[];
  rewrite_suggestions?: string[];
  pass_humanization?: boolean;
  mode?: string;
};

export type OriginalityIssue = {
  issue_type?: string;
  severity?: string;
  description?: string;
  matched_text?: string | null;
  recommendation?: string;
};

export type OriginalityReport = {
  checked?: boolean;
  passed?: boolean;
  similarity_score?: number;
  max_common_sequence_length?: number;
  copied_sentence_count?: number;
  structure_similarity?: number;
  issues?: OriginalityIssue[];
  rewrite_attempted?: boolean;
  rewrite_mode?: string;
  summary?: string;
};

export type ReviewItem = {
  full_name?: string;
  title?: string;
  total_score?: number;
  factual_score?: number;
  title_score?: number;
  structure_score?: number;
  readability_score?: number;
  completeness_score?: number;
  strengths?: string[];
  issues?: string[];
  revision_suggestions?: string[];
  pass_review?: boolean;
  review_mode?: string;
};

export type ReviewSummary = {
  total_count?: number;
  pass_count?: number;
  pass_rate?: string;
  pass_threshold?: number;
  llm_available?: boolean;
  used_llm?: boolean;
  warnings?: string[];
  reviews?: ReviewItem[];
};

export type SelectionReasonItem = {
  repo_full_name?: string;
  bucket?: string;
  reason?: string;
  total_score?: number;
  growth_score?: number;
  velocity_score?: number;
  freshness_score?: number;
  discovery_reason?: string | null;
};

export type SelectionSummary = {
  candidate_count?: number;
  fresh_candidate_count?: number;
  repeated_candidate_count?: number;
  skipped_recent_count?: number;
  cooldown_days?: number;
  allow_recent_fallback?: boolean;
  fallback_repos?: string[];
  new_project_shortage?: boolean;
  selected_repos?: string[];
  selected_repos_with_reason?: SelectionReasonItem[];
  selection_buckets?: Record<string, string[]>;
  growth_selected_count?: number;
  tool_selected_count?: number;
};

export type DashboardResponse = {
  health?: DashboardHealth;
  stats?: DashboardStats;
  run_info?: RunInfo;
  pipeline?: PipelineStage[];
  score_ranking?: ScoreRankingItem[];
  final_articles?: FinalArticleItem[];
  review_summary?: ReviewSummary;
  selection_summary?: SelectionSummary;
};

export type RunDailyParams = {
  limit_per_keyword: number;
  score_top: number;
  research_top: number;
  article_top: number;
  review_threshold: number;
  cooldown_days: number;
  ignore_history: boolean;
  allow_recent_fallback: boolean;
  prefer_growth_projects: boolean;
};

export type RunDailyAsyncParams = RunDailyParams & {
  daily_keywords?: string[];
};

export type UiSettings = {
  run_defaults: RunDailyParams;
  discovery: {
    daily_keywords: string[];
  };
  frontend: {
    default_language: "zh" | "en";
  };
};

export type SettingsResponse = {
  settings: UiSettings;
  source: string;
  exists: boolean;
};

export type NewsItem = {
  id: string;
  title: string;
  title_zh?: string | null;
  url: string;
  source: string;
  source_type: string;
  published_at?: string | null;
  fetched_at: string;
  summary: string;
  summary_zh?: string | null;
  content_text?: string | null;
  content_text_truncated?: boolean;
  content_availability: string;
  language?: string | null;
  topics: string[];
  keywords: string[];
  freshness: string;
  raw_score: number;
  duplicate_key: string;
  translation_status?: "translated" | "skipped" | "failed" | "source_is_chinese" | string;
  translation_error?: string | null;
};

export type NewsCollectionResult = {
  exists?: boolean;
  generated_at: string;
  window_hours: number;
  total_count: number;
  fresh_count: number;
  sources: string[];
  source_counts: Record<string, number>;
  availability_counts: Record<string, number>;
  items: NewsItem[];
  warnings: string[];
};

export type NewsDetailResult = {
  exists?: boolean;
  news_id: string;
  title: string;
  title_zh?: string | null;
  summary: string;
  summary_zh?: string | null;
  url: string;
  source: string;
  source_type: string;
  published_at?: string | null;
  fetched_at: string;
  freshness: string;
  content_text?: string | null;
  content_text_truncated?: boolean;
  content_preview: string;
  content_availability: string;
  extraction_status: "cached" | "refreshed" | "failed" | "skipped" | string;
  extraction_error?: string | null;
  word_count: number;
  original_language?: string | null;
  cover_image_url?: string | null;
  cover_image_source_url?: string | null;
  cover_image_alt?: string | null;
  cover_image_status?: string;
  image_candidates?: NewsImageCandidate[];
};

export type NewsImageCandidate = {
  url: string;
  source_url: string;
  alt?: string | null;
  source_type?: string;
};

export type NewsSelectionItem = {
  news_id: string;
  title: string;
  title_zh?: string | null;
  url: string;
  source: string;
  source_type: string;
  published_at?: string | null;
  content_availability: string;
  role: "primary" | "supporting" | string;
};

export type NewsSelectionContext = {
  exists?: boolean;
  selection_id: string;
  created_at: string;
  updated_at: string;
  primary_news_id: string;
  items: NewsSelectionItem[];
  direction_text?: string | null;
  notes: string[];
  warnings: string[];
};

export type NewsSelectionRequest = {
  news_ids: string[];
  primary_news_id?: string | null;
  direction_text?: string | null;
};

export type NewsArticlePlan = {
  exists?: boolean;
  plan_id: string;
  selection_id: string;
  generated_at: string;
  primary_news_id: string;
  title_candidates: string[];
  recommended_title: string;
  core_angle: string;
  lead_hook: string;
  event_summary: string;
  key_facts: string[];
  valuable_comment_insights?: string[];
  background_context: string[];
  why_it_matters: string[];
  reader_takeaways: string[];
  developer_impact: string[];
  industry_impact: string[];
  article_structure: string[];
  must_include: string[];
  should_avoid: string[];
  source_urls: string[];
  factual_boundaries: string[];
  writing_style: string;
  warnings: string[];
  generation_mode: "llm" | "fallback" | string;
};

export type NewsArticlePlanRequest = {
  selection_id?: string | null;
  use_latest?: boolean;
};

export type NewsArticle = {
  exists?: boolean;
  article_id: string;
  plan_id: string;
  selection_id: string;
  generated_at: string;
  title: string;
  subtitle: string;
  content_markdown: string;
  primary_news_id: string;
  source_news_ids: string[];
  source_urls: string[];
  word_count: number;
  generation_mode: "llm" | "fallback" | string;
  used_full_text_count: number;
  used_summary_only_count: number;
  warnings: string[];
  factual_boundaries: string[];
  publish_ready: boolean;
  quality_report?: NewsArticleQualityReport | null;
  quality_score?: number;
  quality_publish_ready?: boolean;
  publish_polished?: boolean;
  publish_package_path?: string | null;
  cover_image_url?: string | null;
  cover_image_source_url?: string | null;
  cover_image_alt?: string | null;
  cover_image_status?: string;
};

export type NewsArticleListItem = {
  article_id: string;
  title?: string;
  subtitle?: string;
  generated_at?: string;
  word_count?: number;
  generation_mode?: string;
  publish_ready?: boolean;
  quality_score?: number | null;
  quality_publish_ready?: boolean;
  publish_polished?: boolean;
  publish_package_path?: string | null;
  cover_image_url?: string | null;
  cover_image_source_url?: string | null;
  cover_image_alt?: string | null;
  cover_image_status?: string;
  content_available?: boolean;
  report_available?: boolean;
  publish_available?: boolean;
  package_available?: boolean;
};

export type NewsArticleListResponse = {
  exists?: boolean;
  articles?: NewsArticleListItem[];
};

export type NewsArticleWriteRequest = {
  plan_id?: string | null;
  use_latest?: boolean;
};

export type NewsArticleQualityIssue = {
  issue_type?: string;
  severity?: "low" | "medium" | "high" | string;
  description?: string;
  suggestion?: string;
  evidence?: string | null;
};

export type NewsArticleQualityReport = {
  article_id?: string;
  title?: string;
  total_score?: number;
  publish_ready?: boolean;
  title_score?: number;
  opening_score?: number;
  factual_integrity_score?: number;
  source_link_score?: number;
  insight_score?: number;
  readability_score?: number;
  originality_score?: number;
  human_tone_score?: number;
  structure_naturalness_score?: number;
  issues?: NewsArticleQualityIssue[];
  strengths?: string[];
  rewrite_recommendations?: string[];
  summary?: string;
};

export type NewsArticleReviewRequest = {
  article_id?: string | null;
  use_latest?: boolean;
  threshold?: number;
  polish?: boolean;
};

export type NewsCollectRequest = {
  hours: number;
  limit: number;
  sources?: string[];
  keywords?: string[];
  include_fulltext: boolean;
  translate?: boolean;
  translate_limit?: number;
};

export type NewsScore = {
  news_id: string;
  title: string;
  title_zh?: string | null;
  url: string;
  source: string;
  source_type: string;
  category: string;
  importance_score: number;
  freshness_score: number;
  source_score: number;
  relevance_score: number;
  discussion_score: number;
  writing_value_score: number;
  total_score: number;
  recommended: boolean;
  recommended_section: string;
  reasons: string[];
  warnings: string[];
  keywords: string[];
};

export type NewsScoringResult = {
  exists?: boolean;
  generated_at: string;
  total_count: number;
  recommended_count: number;
  category_counts: Record<string, number>;
  section_counts: Record<string, number>;
  scores: NewsScore[];
  warnings: string[];
};

export type NewsScoreRequest = {
  top: number;
  min_score: number;
};

export type NewsEventCard = {
  event_id: string;
  event_title: string;
  event_title_zh: string;
  event_summary: string;
  event_summary_zh: string;
  category: string;
  recommended_section: string;
  total_score: number;
  importance_score: number;
  freshness_score: number;
  source_count: number;
  sources: string[];
  source_types: string[];
  urls: string[];
  primary_url: string;
  primary_source: string;
  published_at?: string | null;
  latest_published_at?: string | null;
  freshness: string;
  keywords: string[];
  related_news_ids: string[];
  related_titles: string[];
  reasons: string[];
  warnings: string[];
  content_availability: string;
};

export type NewsEventResult = {
  exists?: boolean;
  generated_at: string;
  total_news_count: number;
  event_count: number;
  recommended_event_count: number;
  section_counts: Record<string, number>;
  category_counts: Record<string, number>;
  events: NewsEventCard[];
  warnings: string[];
};

export type NewsEventBuildRequest = {
  top: number;
  min_score: number;
  similarity_threshold: number;
};

export type NewsDigestSection = {
  section_name: string;
  event_ids: string[];
  summary: string;
};

export type NewsDigestQualityIssue = {
  issue_type?: string;
  severity?: "low" | "medium" | "high" | string;
  description?: string;
  suggestion?: string;
  evidence?: string | null;
};

export type NewsDigestQualityReport = {
  title?: string;
  total_score?: number;
  publish_ready?: boolean;
  freshness_score?: number;
  source_integrity_score?: number;
  section_balance_score?: number;
  insight_score?: number;
  readability_score?: number;
  originality_score?: number;
  human_tone_score?: number;
  link_integrity_score?: number;
  issues?: NewsDigestQualityIssue[];
  strengths?: string[];
  rewrite_recommendations?: string[];
  summary?: string;
};

export type NewsDigestArticle = {
  exists?: boolean;
  title: string;
  subtitle: string;
  date: string;
  content_markdown: string;
  event_count: number;
  sections: string[];
  section_details?: NewsDigestSection[];
  source_event_ids: string[];
  source_urls: string[];
  generation_mode: "llm" | "fallback" | string;
  warnings: string[];
  word_count: number;
  quality_notes: string[];
  quality_report?: NewsDigestQualityReport | null;
  quality_score?: number;
  publish_ready?: boolean;
  polished?: boolean;
  package_path?: string | null;
};

export type NewsDigestWriteRequest = {
  top: number;
  date?: string | null;
};

export type NewsDigestReviewRequest = {
  threshold?: number;
  polish?: boolean;
};

export type NewsReportContent = {
  exists?: boolean;
  content_markdown?: string;
  path?: string | null;
  message?: string;
};

export type RunDailyResponse = {
  run_id?: string;
  status?: string;
  output_dir?: string;
  date?: string;
  message?: string;
  [key: string]: unknown;
};

export type RunDailyAsyncResponse = {
  job_id: string;
  status: "queued" | "running" | "success" | "failed" | string;
};

export type CustomArticleRequest = {
  repo_url: string;
  direction?: string;
  reference_texts: string[];
  reference_source_names: string[];
};

export type StyleReferenceProfile = {
  summary?: string;
  source_names?: string[];
  raw_count?: number;
  tone_traits?: string[];
  rhythm_traits?: string[];
  reader_relationship?: string[];
  title_patterns?: string[];
  opening_patterns?: string[];
  originality_rules?: string[];
  do_not_copy?: string[];
  warnings?: string[];
  [key: string]: unknown;
};

export type CustomArticleResult = {
  exists?: boolean;
  status?: string;
  message?: string;
  snapshot_path?: string;
  generated_at?: string;
  repo_url?: string;
  normalized_repo_url?: string;
  owner?: string;
  repo?: string;
  full_name?: string;
  direction_text?: string;
  style_reference_profile?: StyleReferenceProfile | null;
  wechat_pattern?: WechatArticlePattern | null;
  content_plan?: ContentPlanItem | null;
  reference_source_names?: string[];
  reference_text_count?: number;
  originality_report?: OriginalityReport | null;
  originality_checked?: boolean;
  originality_passed?: boolean;
  article_quality_report?: ArticleQualityReport | null;
  quality_score?: number;
  quality_publish_ready?: boolean;
  output_markdown_path?: string;
  report_path?: string;
  package_path?: string;
  packaged_article_path?: string;
  packaged_article_available?: boolean;
  selected_readme_images?: string[];
  asset_count?: number;
  final_article?: FinalArticleItem & {
    content_markdown?: string;
    html_url?: string;
  };
  review?: ReviewItem;
  warnings?: string[];
};

export type CustomArticleMarkdownContent = {
  exists?: boolean;
  full_name?: string;
  status?: string;
  content_markdown?: string;
  path?: string | null;
  message?: string;
};

export type JobEvent = {
  type?: string;
  stage?: string;
  message?: string;
  time?: string;
  error?: string;
  result?: Record<string, unknown>;
};

export type JobLog = {
  time?: string;
  stage?: string | null;
  type?: string;
  message?: string;
};

export type JobStatus = {
  job_id: string;
  status: "queued" | "running" | "success" | "failed" | string;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  current_stage?: string | null;
  stages?: PipelineStage[];
  logs?: JobLog[];
  result?: Record<string, unknown> | null;
  error?: string | null;
};

export type FinalArticleContent = {
  safe_name?: string;
  content_markdown?: string;
  path?: string;
};

export type ReportContent = {
  report_name?: string;
  content_markdown?: string;
  path?: string;
};

export type OutputDateSummary = {
  date: string;
  path: string;
  reports: string[];
  final_articles_count: number;
  articles_count: number;
  packages_count?: number;
  assets_count?: number;
};

export type OutputReportItem = {
  name: string;
  filename: string;
  path: string;
  exists: boolean;
  size_bytes?: number;
};

export type OutputFileItem = {
  safe_name: string;
  filename: string;
  path: string;
  title?: string;
  size_bytes: number;
};

export type OutputAssetItem = {
  safe_name: string;
  filename: string;
  path: string;
  asset_type?: string;
  size_bytes: number;
};

export type OutputDateDetail = {
  date: string;
  reports: OutputReportItem[];
  articles: OutputFileItem[];
  final_articles: OutputFileItem[];
  packages?: OutputFileItem[];
  assets?: OutputAssetItem[];
};

export type OutputMarkdownContent = {
  date?: string;
  report_name?: string;
  safe_name?: string;
  filename?: string;
  content_markdown?: string;
  path?: string;
};

export type SnapshotName =
  | "discovery"
  | "score"
  | "research"
  | "angles"
  | "content_plan"
  | "articles"
  | "reviews"
  | "humanization"
  | "publish_polish"
  | "article_quality"
  | "final_articles"
  | "article_packages"
  | "news"
  | "news_scores"
  | "news_events"
  | "news_digest"
  | "news_digest_review";

export type VisualAsset = {
  full_name?: string;
  asset_id?: string;
  asset_type?: string;
  title?: string;
  description?: string;
  source_url?: string | null;
  output_path?: string | null;
  format?: "png" | "svg" | "md" | "prompt" | string;
  status?: "planned" | "generated" | "failed" | "skipped" | string;
  error?: string | null;
};

export type ArticlePackage = {
  full_name?: string;
  title?: string;
  article_path?: string;
  packaged_article_path?: string;
  assets?: VisualAsset[];
  cover_prompt?: string;
  package_dir?: string;
  status?: string;
  notes?: string[];
};

export type ArticlePackagesSnapshot = {
  generated_at?: string;
  total_count?: number;
  packages?: ArticlePackage[];
};

export type PackageArticlesRequest = {
  top?: number | null;
  safe_names?: string[];
  full_names?: string[];
};

export type PackageArticlesResponse = {
  status?: string;
  total_count?: number;
  packages?: ArticlePackage[];
};

export type CandidateItem = {
  name?: string;
  full_name?: string;
  owner?: string;
  html_url?: string;
  url?: string;
  description?: string;
  stars?: number;
  stargazers_count?: number;
  watchers_count?: number;
  forks?: number;
  forks_count?: number;
  open_issues?: number;
  language?: string;
  topics?: string[];
  updated_at?: string;
  pushed_at?: string;
  created_at?: string;
  license_name?: string;
  homepage?: string;
  discovery_reason?: string | null;
};

export type DiscoverySnapshot = {
  generated_at?: string;
  keywords?: string[];
  total_count?: number;
  candidates?: CandidateItem[];
};

export type ScoreSnapshot = {
  generated_at?: string;
  total_count?: number;
  scores?: ScoreRankingItem[];
};

export type ReleaseItem = {
  tag_name?: string;
  name?: string;
  published_at?: string;
  html_url?: string;
  body?: string;
};

export type IssueItem = {
  title?: string;
  html_url?: string;
  created_at?: string;
  comments?: number;
};

export type ResearchNote = {
  full_name?: string;
  html_url?: string;
  description?: string;
  stars?: number;
  forks?: number;
  language?: string;
  topics?: string[];
  license_name?: string;
  pushed_at?: string;
  readme_summary?: string;
  readme_key_points?: string[];
  releases?: ReleaseItem[];
  open_issues?: IssueItem[];
  source_links?: string[];
  risks?: string[];
  author_profile?: AuthorProfile | null;
  project_links?: ProjectLinks | null;
  readme_images?: string[];
  readme_links?: string[];
  tool_use_cases?: string[];
  project_kind?: string | null;
};

export type AuthorProfile = {
  login?: string;
  type?: string | null;
  name?: string | null;
  html_url?: string;
  avatar_url?: string | null;
  bio?: string | null;
  company?: string | null;
  blog?: string | null;
  location?: string | null;
  twitter_username?: string | null;
  public_repos?: number | null;
  followers?: number | null;
  created_at?: string | null;
  source?: string;
};

export type ProjectLinks = {
  homepage?: string | null;
  documentation?: string[];
  demo?: string[];
  examples?: string[];
  website?: string[];
  images?: string[];
  videos?: string[];
  badges?: string[];
};

export type ResearchSnapshot = {
  generated_at?: string;
  total_count?: number;
  notes?: ResearchNote[];
};

export type TitleCandidate = {
  title?: string;
  style?: string;
  reason?: string;
  risk?: string;
};

export type TopicAngle = {
  full_name?: string;
  html_url?: string;
  project_name?: string;
  selected_angle?: string;
  one_liner?: string;
  target_readers?: string[];
  reader_pain_points?: string[];
  selling_points?: string[];
  title_candidates?: TitleCandidate[];
  opening_hook?: string;
  article_outline?: string[];
  cover_prompt?: string;
  source_links?: string[];
  factual_warnings?: string[];
};

export type FactCard = {
  full_name?: string;
  claim?: string;
  category?: string;
  source?: string;
  source_type?: string;
  confidence?: string;
  publishable?: boolean;
  note?: string | null;
};

export type ProjectInsight = {
  full_name?: string;
  project_name?: string;
  plain_summary?: string;
  problem_solved?: string;
  core_value?: string;
  ideal_users?: string[];
  use_cases?: string[];
  standout_points?: string[];
  adoption_notes?: string[];
  local_context?: string;
  not_to_overclaim?: string[];
  source_fact_ids?: number[];
};

export type FeatureAdvantage = {
  feature?: string;
  advantage?: string;
  reader_interest?: string;
  evidence?: string;
  emphasis?: "high" | "medium" | "low" | string;
};

export type ProjectAppeal = {
  full_name?: string;
  project_name?: string;
  appeal_summary?: string;
  primary_hook?: string;
  feature_advantages?: FeatureAdvantage[];
  top_selling_points?: string[];
  reader_interest_points?: string[];
  practical_scenarios?: string[];
  differentiation_points?: string[];
  avoid_overemphasis?: string[];
  recommended_focus?: string[];
  confidence?: "high" | "medium" | "low" | string;
};

export type ProjectImpact = {
  full_name?: string;
  core_effect?: string;
  effect_summary?: string;
  concrete_outcomes?: string[];
  before_after_examples?: string[];
  usage_examples?: string[];
  user_benefits?: string[];
  measurable_signals?: string[];
  article_expansion_points?: string[];
  weak_or_unknown_effects?: string[];
};

export type WechatArticlePattern = {
  pattern_type?:
    | "concept_practice"
    | "hot_project"
    | "demo_scene"
    | "practical_tool"
    | "platform_workbench"
    | string;
  opening_strategy?:
    | "trend_hook"
    | "pain_hook"
    | "concept_hook"
    | "author_hook"
    | "personal_trial_hook"
    | string;
  title_formula?: string;
  lead_hook?: string;
  key_storyline?: string;
  required_effect_points?: string[];
  required_examples?: string[];
  allowed_colloquial_phrases?: string[];
  banned_phrases?: string[];
  image_placement_hints?: string[];
  ending_style?: string;
};

export type ContentPlanItem = {
  full_name?: string;
  project_kind?: string | null;
  tool_use_cases?: string[];
  author_profile?: AuthorProfile | null;
  project_links?: ProjectLinks | null;
  facts?: FactCard[];
  insight?: ProjectInsight | null;
  brief?: Record<string, unknown> | null;
  appeal?: ProjectAppeal | null;
  impact?: ProjectImpact | null;
  wechat_pattern?: WechatArticlePattern | null;
  planning_mode?: string;
  warnings?: string[];
};

export type ContentPlanSnapshot = {
  generated_at?: string;
  total_count?: number;
  llm_available?: boolean;
  used_llm?: boolean;
  warnings?: string[];
  plans?: ContentPlanItem[];
};

export type AnglesSnapshot = {
  generated_at?: string;
  total_count?: number;
  llm_available?: boolean;
  used_llm?: boolean;
  warnings?: string[];
  angles?: TopicAngle[];
};

export type ArticleSnapshotItem = FinalArticleItem & {
  content_markdown?: string;
  cover_prompt?: string;
  source_links?: string[];
  factual_warnings?: string[];
  review?: ReviewItem;
  revision_mode?: string;
  generation_mode?: string;
  created_at?: string;
};

export type ArticlesSnapshot = {
  generated_at?: string;
  total_count?: number;
  articles?: ArticleSnapshotItem[];
  warnings?: string[];
};

export type ReviewsSnapshot = ReviewSummary & {
  generated_at?: string;
  total_count?: number;
};

export type RunHistoryItem = {
  run_id?: string;
  date?: string;
  status?: string;
  started_at?: string;
  finished_at?: string;
  error?: string | null;
  file?: string;
  stages?: PipelineStage[];
  output_dir?: string;
  selection_summary?: SelectionSummary;
};

export type RunsResponse = {
  runs?: RunHistoryItem[];
};

export type LatestRunResponse = RunHistoryItem & {
  exists?: boolean;
  message?: string;
  current_stage?: string | null;
  snapshot_files?: Record<string, string>;
  final_article_files?: string[];
  keywords?: string[];
};

export type ConfigStatus = {
  github_token_configured?: boolean;
  llm_configured?: boolean;
  output_dir?: string;
  workspace_dir?: string;
  daily_keywords?: string[];
};

export type PageKey =
  | "dashboard"
  | "customArticle"
  | "candidates"
  | "scoreRanking"
  | "researchNotes"
  | "topicAngles"
  | "articles"
  | "aiNews"
  | "reports"
  | "reviews"
  | "runsHistory"
  | "settings";
