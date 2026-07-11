import { Check, Clipboard, Download, ExternalLink, Filter, RefreshCw, Save, Sparkles, Star, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  buildNewsEvents,
  collectNews,
  createNewsArticlePlan,
  createNewsSelection,
  fetchNewsDetail,
  fetchLatestNewsArticlePlan,
  fetchLatestNews,
  fetchNewsDigest,
  fetchNewsDigestContent,
  fetchNewsDigestPackage,
  fetchNewsDigestReview,
  fetchNewsEvents,
  fetchNewsEventsReport,
  fetchNewsReport,
  fetchNewsScores,
  fetchNewsScoresReport,
  refreshNewsDetail,
  scoreNews,
  reviewNewsDigest,
  writeNewsDigest,
} from "../api";
import { copyText, downloadMarkdown } from "../fileUtils";
import type { Translation } from "../i18n";
import type {
  NewsCollectRequest,
  NewsArticlePlan,
  NewsCollectionResult,
  NewsDetailResult,
  NewsDigestArticle,
  NewsDigestQualityReport,
  NewsEventCard,
  NewsEventResult,
  NewsItem,
  NewsScore,
  NewsSelectionContext,
  NewsScoringResult,
} from "../types";
import { asArray, formatDate } from "./pageUtils";

type AINewsPageProps = {
  t: Translation;
};

type NewsFilters = {
  source: string;
  sourceType: string;
  freshness: string;
  availability: string;
  translationStatus: string;
  scoreView: string;
  category: string;
  section: string;
  eventCategory: string;
  eventSection: string;
  eventSourceCount: string;
  search: string;
};

type NewsTab = "list" | "recommended" | "events" | "articlePlan" | "digest" | "collectionReport" | "scoreReport" | "eventReport";

const SOURCE_OPTIONS = ["official", "hn", "arxiv", "gdelt", "rsshub"];
const MAX_SELECTED_NEWS = 5;
const DEFAULT_FILTERS: NewsFilters = {
  source: "",
  sourceType: "",
  freshness: "",
  availability: "",
  translationStatus: "",
  scoreView: "all",
  category: "",
  section: "",
  eventCategory: "",
  eventSection: "",
  eventSourceCount: "all",
  search: "",
};

const emptyNewsResult = (): NewsCollectionResult => ({
  exists: false,
  generated_at: "",
  window_hours: 24,
  total_count: 0,
  fresh_count: 0,
  sources: [],
  source_counts: {},
  availability_counts: {},
  items: [],
  warnings: [],
});

const emptyScoringResult = (): NewsScoringResult => ({
  exists: false,
  generated_at: "",
  total_count: 0,
  recommended_count: 0,
  category_counts: {},
  section_counts: {},
  scores: [],
  warnings: [],
});

const emptyEventResult = (): NewsEventResult => ({
  exists: false,
  generated_at: "",
  total_news_count: 0,
  event_count: 0,
  recommended_event_count: 0,
  section_counts: {},
  category_counts: {},
  events: [],
  warnings: [],
});

const emptyDigestArticle = (): NewsDigestArticle => ({
  exists: false,
  title: "",
  subtitle: "",
  date: "",
  content_markdown: "",
  event_count: 0,
  sections: [],
  section_details: [],
  source_event_ids: [],
  source_urls: [],
  generation_mode: "fallback",
  warnings: [],
  word_count: 0,
  quality_notes: [],
  quality_report: null,
  quality_score: 0,
  publish_ready: false,
  polished: false,
  package_path: null,
});

const emptyArticlePlan = (): NewsArticlePlan => ({
  exists: false,
  plan_id: "",
  selection_id: "",
  generated_at: "",
  primary_news_id: "",
  title_candidates: [],
  recommended_title: "",
  core_angle: "",
  lead_hook: "",
  event_summary: "",
  key_facts: [],
  background_context: [],
  why_it_matters: [],
  reader_takeaways: [],
  developer_impact: [],
  industry_impact: [],
  article_structure: [],
  must_include: [],
  should_avoid: [],
  source_urls: [],
  factual_boundaries: [],
  writing_style: "",
  warnings: [],
  generation_mode: "fallback",
});

function uniqueValues(items: NewsItem[], key: keyof Pick<NewsItem, "source" | "source_type" | "freshness" | "content_availability">) {
  return Array.from(new Set(items.map((item) => item[key]).filter(Boolean))).sort();
}

function uniqueScoreValues(items: NewsScore[], key: keyof Pick<NewsScore, "category" | "recommended_section">) {
  return Array.from(new Set(items.map((item) => item[key]).filter(Boolean))).sort();
}

function uniqueEventValues(items: NewsEventCard[], key: keyof Pick<NewsEventCard, "category" | "recommended_section">) {
  return Array.from(new Set(items.map((item) => item[key]).filter(Boolean))).sort();
}

function availabilityLabel(value: string, t: Translation) {
  if (value === "full_text") return t.news.fullText;
  if (value === "summary_only") return t.news.summaryOnly;
  if (value === "metadata_only") return t.news.metadataOnly;
  return value || "-";
}

function translationStatusLabel(value: string | undefined | null, t: Translation) {
  if (value === "translated") return t.news.translated;
  if (value === "skipped") return t.news.translationSkipped;
  if (value === "failed") return t.news.translationFailed;
  if (value === "source_is_chinese") return t.news.sourceIsChinese;
  return value || "-";
}

function extractionStatusLabel(value: string | undefined | null, t: Translation) {
  if (value === "cached") return t.news.extractionCached;
  if (value === "refreshed") return t.news.extractionRefreshed;
  if (value === "failed") return t.news.extractionFailed;
  if (value === "skipped") return t.news.extractionSkipped;
  return value || "-";
}

function normalizeKeywords(value: string) {
  return value
    .split(",")
    .map((keyword) => keyword.trim())
    .filter(Boolean);
}

function latestPublishedAt(items: NewsItem[]) {
  const timestamps = items
    .map((item) => item.published_at || item.fetched_at)
    .map((value) => (value ? new Date(value).getTime() : Number.NaN))
    .filter((value) => !Number.isNaN(value));
  if (!timestamps.length) return "";
  return new Date(Math.max(...timestamps)).toISOString();
}

function markdownList(values: string[]) {
  const cleaned = asArray(values).filter(Boolean);
  return cleaned.length ? cleaned.map((value) => `- ${value}`).join("\n") : "- -";
}

function articlePlanToMarkdown(plan: NewsArticlePlan) {
  return [
    "# AI 新闻文章策划",
    "",
    `- Plan ID: ${plan.plan_id || "-"}`,
    `- Selection ID: ${plan.selection_id || "-"}`,
    `- Primary News ID: ${plan.primary_news_id || "-"}`,
    `- Generated at: ${plan.generated_at || "-"}`,
    `- Generation mode: ${plan.generation_mode || "-"}`,
    "",
    "## 推荐标题",
    "",
    plan.recommended_title || "-",
    "",
    "## 标题候选",
    "",
    markdownList(plan.title_candidates),
    "",
    "## 核心角度",
    "",
    plan.core_angle || "-",
    "",
    "## 开头钩子",
    "",
    plan.lead_hook || "-",
    "",
    "## 事件摘要",
    "",
    plan.event_summary || "-",
    "",
    "## 关键事实",
    "",
    markdownList(plan.key_facts),
    "",
    "## 背景信息",
    "",
    markdownList(plan.background_context),
    "",
    "## 为什么重要",
    "",
    markdownList(plan.why_it_matters),
    "",
    "## 读者收获",
    "",
    markdownList(plan.reader_takeaways),
    "",
    "## 开发者影响",
    "",
    markdownList(plan.developer_impact),
    "",
    "## 行业影响",
    "",
    markdownList(plan.industry_impact),
    "",
    "## 文章结构",
    "",
    markdownList(plan.article_structure),
    "",
    "## 必须包含",
    "",
    markdownList(plan.must_include),
    "",
    "## 应避免",
    "",
    markdownList(plan.should_avoid),
    "",
    "## 事实边界",
    "",
    markdownList(plan.factual_boundaries),
    "",
    "## 来源链接",
    "",
    markdownList(plan.source_urls),
    "",
    "## Warnings",
    "",
    markdownList(plan.warnings),
  ].join("\n");
}

export function AINewsPage({ t }: AINewsPageProps) {
  const [news, setNews] = useState<NewsCollectionResult>(() => emptyNewsResult());
  const [scores, setScores] = useState<NewsScoringResult>(() => emptyScoringResult());
  const [events, setEvents] = useState<NewsEventResult>(() => emptyEventResult());
  const [articlePlan, setArticlePlan] = useState<NewsArticlePlan>(() => emptyArticlePlan());
  const [digest, setDigest] = useState<NewsDigestArticle>(() => emptyDigestArticle());
  const [digestReview, setDigestReview] = useState<NewsDigestQualityReport | null>(null);
  const [digestPackage, setDigestPackage] = useState("");
  const [digestPackagePath, setDigestPackagePath] = useState("");
  const [digestPath, setDigestPath] = useState("");
  const [report, setReport] = useState("");
  const [reportPath, setReportPath] = useState("");
  const [scoreReport, setScoreReport] = useState("");
  const [scoreReportPath, setScoreReportPath] = useState("");
  const [eventReport, setEventReport] = useState("");
  const [eventReportPath, setEventReportPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [buildingEvents, setBuildingEvents] = useState(false);
  const [planningArticle, setPlanningArticle] = useState(false);
  const [writingDigest, setWritingDigest] = useState(false);
  const [reviewingDigest, setReviewingDigest] = useState(false);
  const [error, setError] = useState("");
  const [reportError, setReportError] = useState("");
  const [message, setMessage] = useState("");
  const [activeTab, setActiveTab] = useState<NewsTab>("list");
  const [hours, setHours] = useState(24);
  const [limit, setLimit] = useState(50);
  const [includeFulltext, setIncludeFulltext] = useState(false);
  const [translate, setTranslate] = useState(true);
  const [translateLimit, setTranslateLimit] = useState(50);
  const [scoreTop, setScoreTop] = useState(20);
  const [minScore, setMinScore] = useState(60);
  const [eventTop, setEventTop] = useState(20);
  const [eventMinScore, setEventMinScore] = useState(60);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.55);
  const [digestTop, setDigestTop] = useState(12);
  const [digestReviewThreshold, setDigestReviewThreshold] = useState(80);
  const [digestPolish, setDigestPolish] = useState(true);
  const [keywords, setKeywords] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>(SOURCE_OPTIONS);
  const [filters, setFilters] = useState<NewsFilters>(DEFAULT_FILTERS);
  const [selectedNewsId, setSelectedNewsId] = useState("");
  const [newsDetail, setNewsDetail] = useState<NewsDetailResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailRefreshing, setDetailRefreshing] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [selectedNewsIds, setSelectedNewsIds] = useState<string[]>([]);
  const [primaryNewsId, setPrimaryNewsId] = useState("");
  const [directionText, setDirectionText] = useState("");
  const [savingSelection, setSavingSelection] = useState(false);
  const [selectionError, setSelectionError] = useState("");
  const [savedSelection, setSavedSelection] = useState<NewsSelectionContext | null>(null);

  const flash = useCallback((text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage((current) => (current === text ? "" : current)), 3000);
  }, []);

  const loadNews = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchLatestNews();
      setNews({
        ...emptyNewsResult(),
        ...payload,
        items: asArray(payload.items),
        warnings: asArray(payload.warnings),
        sources: asArray(payload.sources),
        source_counts: payload.source_counts || {},
        availability_counts: payload.availability_counts || {},
      });
      setError("");
    } catch (err) {
      setNews(emptyNewsResult());
      setError(err instanceof Error ? err.message : t.news.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [t.news.loadFailed]);

  const loadReport = useCallback(async () => {
    try {
      const payload = await fetchNewsReport();
      setReport(payload.content_markdown || "");
      setReportPath(payload.path || "");
      setReportError("");
    } catch (err) {
      setReport("");
      setReportPath("");
      if (err instanceof ApiError && err.status === 404) {
        setReportError("");
      } else {
        setReportError(err instanceof Error ? err.message : t.messages.reportFailed);
      }
    }
  }, [t.messages.reportFailed]);

  const loadScores = useCallback(async () => {
    try {
      const payload = await fetchNewsScores();
      setScores({
        ...emptyScoringResult(),
        ...payload,
        scores: asArray(payload.scores),
        warnings: asArray(payload.warnings),
        category_counts: payload.category_counts || {},
        section_counts: payload.section_counts || {},
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setScores(emptyScoringResult());
      } else {
        setError(err instanceof Error ? err.message : t.news.scoreLoadFailed);
      }
    }
  }, [t.news.scoreLoadFailed]);

  const loadScoreReport = useCallback(async () => {
    try {
      const payload = await fetchNewsScoresReport();
      setScoreReport(payload.content_markdown || "");
      setScoreReportPath(payload.path || "");
    } catch (err) {
      setScoreReport("");
      setScoreReportPath("");
      if (!(err instanceof ApiError && err.status === 404)) {
        setReportError(err instanceof Error ? err.message : t.messages.reportFailed);
      }
    }
  }, [t.messages.reportFailed]);

  const loadEvents = useCallback(async () => {
    try {
      const payload = await fetchNewsEvents();
      setEvents({
        ...emptyEventResult(),
        ...payload,
        events: asArray(payload.events),
        warnings: asArray(payload.warnings),
        category_counts: payload.category_counts || {},
        section_counts: payload.section_counts || {},
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setEvents(emptyEventResult());
      } else {
        setError(err instanceof Error ? err.message : t.news.eventLoadFailed);
      }
    }
  }, [t.news.eventLoadFailed]);

  const loadEventReport = useCallback(async () => {
    try {
      const payload = await fetchNewsEventsReport();
      setEventReport(payload.content_markdown || "");
      setEventReportPath(payload.path || "");
    } catch (err) {
      setEventReport("");
      setEventReportPath("");
      if (!(err instanceof ApiError && err.status === 404)) {
        setReportError(err instanceof Error ? err.message : t.messages.reportFailed);
      }
    }
  }, [t.messages.reportFailed]);

  const loadArticlePlan = useCallback(async () => {
    try {
      const payload = await fetchLatestNewsArticlePlan();
      setArticlePlan({
        ...emptyArticlePlan(),
        ...payload,
        title_candidates: asArray(payload.title_candidates),
        key_facts: asArray(payload.key_facts),
        background_context: asArray(payload.background_context),
        why_it_matters: asArray(payload.why_it_matters),
        reader_takeaways: asArray(payload.reader_takeaways),
        developer_impact: asArray(payload.developer_impact),
        industry_impact: asArray(payload.industry_impact),
        article_structure: asArray(payload.article_structure),
        must_include: asArray(payload.must_include),
        should_avoid: asArray(payload.should_avoid),
        source_urls: asArray(payload.source_urls),
        factual_boundaries: asArray(payload.factual_boundaries),
        warnings: asArray(payload.warnings),
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setArticlePlan(emptyArticlePlan());
      } else {
        setError(err instanceof Error ? err.message : t.news.articlePlanLoadFailed);
      }
    }
  }, [t.news.articlePlanLoadFailed]);

  const loadDigest = useCallback(async () => {
    try {
      const [payload, contentPayload] = await Promise.all([fetchNewsDigest(), fetchNewsDigestContent()]);
      setDigest({
        ...emptyDigestArticle(),
        ...payload,
        content_markdown: contentPayload.content_markdown || payload.content_markdown || "",
        sections: asArray(payload.sections),
        section_details: asArray(payload.section_details),
        source_event_ids: asArray(payload.source_event_ids),
        source_urls: asArray(payload.source_urls),
        warnings: asArray(payload.warnings),
        quality_notes: asArray(payload.quality_notes),
        quality_report: payload.quality_report || null,
      });
      setDigestReview(payload.quality_report || null);
      setDigestPath(contentPayload.path || "");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setDigest(emptyDigestArticle());
        setDigestReview(null);
        setDigestPath("");
      } else {
        setError(err instanceof Error ? err.message : t.news.digestLoadFailed);
      }
    }
  }, [t.news.digestLoadFailed]);

  const loadDigestReview = useCallback(async () => {
    try {
      const payload = await fetchNewsDigestReview();
      const report = payload.quality_report || (payload as unknown as NewsDigestQualityReport);
      setDigestReview(report && payload.exists !== false ? report : null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setDigestReview(null);
      } else {
        setError(err instanceof Error ? err.message : t.news.digestReviewLoadFailed);
      }
    }
  }, [t.news.digestReviewLoadFailed]);

  const loadDigestPackage = useCallback(async () => {
    try {
      const payload = await fetchNewsDigestPackage();
      setDigestPackage(payload.content_markdown || "");
      setDigestPackagePath(payload.path || "");
    } catch (err) {
      setDigestPackage("");
      setDigestPackagePath("");
      if (!(err instanceof ApiError && err.status === 404)) {
        setError(err instanceof Error ? err.message : t.news.digestPackageLoadFailed);
      }
    }
  }, [t.news.digestPackageLoadFailed]);

  const refreshAll = useCallback(async () => {
    await Promise.all([
      loadNews(),
      loadReport(),
      loadScores(),
      loadScoreReport(),
      loadEvents(),
      loadEventReport(),
      loadArticlePlan(),
      loadDigest(),
      loadDigestReview(),
      loadDigestPackage(),
    ]);
  }, [
    loadNews,
    loadReport,
    loadScores,
    loadScoreReport,
    loadEvents,
    loadEventReport,
    loadArticlePlan,
    loadDigest,
    loadDigestReview,
    loadDigestPackage,
  ]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const items = useMemo(() => asArray(news.items), [news.items]);
  const itemById = useMemo(() => {
    const byId = new Map<string, NewsItem>();
    items.forEach((item) => byId.set(item.id, item));
    return byId;
  }, [items]);
  const selectedNewsIdSet = useMemo(() => new Set(selectedNewsIds), [selectedNewsIds]);
  const selectedNewsItems = useMemo(
    () => selectedNewsIds.map((newsId) => itemById.get(newsId)).filter((item): item is NewsItem => Boolean(item)),
    [itemById, selectedNewsIds],
  );
  const scoreItems = useMemo(() => asArray(scores.scores), [scores.scores]);
  const eventItems = useMemo(() => asArray(events.events), [events.events]);
  const scoreByNewsId = useMemo(() => {
    const byId = new Map<string, NewsScore>();
    scoreItems.forEach((score) => byId.set(score.news_id, score));
    return byId;
  }, [scoreItems]);
  const sourceOptions = useMemo(() => uniqueValues(items, "source"), [items]);
  const sourceTypeOptions = useMemo(() => uniqueValues(items, "source_type"), [items]);
  const freshnessOptions = useMemo(() => uniqueValues(items, "freshness"), [items]);
  const availabilityOptions = useMemo(() => uniqueValues(items, "content_availability"), [items]);
  const categoryOptions = useMemo(() => uniqueScoreValues(scoreItems, "category"), [scoreItems]);
  const sectionOptions = useMemo(() => uniqueScoreValues(scoreItems, "recommended_section"), [scoreItems]);
  const eventCategoryOptions = useMemo(() => uniqueEventValues(eventItems, "category"), [eventItems]);
  const eventSectionOptions = useMemo(() => uniqueEventValues(eventItems, "recommended_section"), [eventItems]);
  const translationStatusOptions = useMemo(
    () => Array.from(new Set(items.map((item) => item.translation_status || "skipped"))).sort(),
    [items],
  );
  const latestDate = useMemo(() => latestPublishedAt(items), [items]);
  const translatedCount = useMemo(
    () => items.filter((item) => item.translation_status === "translated").length,
    [items],
  );
  const averageScore = useMemo(() => {
    if (!scoreItems.length) return 0;
    return scoreItems.reduce((sum, score) => sum + Number(score.total_score || 0), 0) / scoreItems.length;
  }, [scoreItems]);
  const topCategory = useMemo(() => {
    const entries = Object.entries(scores.category_counts || {}).sort((a, b) => b[1] - a[1]);
    return entries[0]?.[0] || "-";
  }, [scores.category_counts]);
  const filteredEvents = useMemo(() => {
    const search = filters.search.trim().toLowerCase();
    return eventItems
      .filter((event) => {
        if (filters.eventCategory && event.category !== filters.eventCategory) return false;
        if (filters.eventSection && event.recommended_section !== filters.eventSection) return false;
        if (filters.eventSourceCount === "multi" && Number(event.source_count || 0) < 2) return false;
        const searchable = `${event.event_title_zh || ""} ${event.event_title || ""} ${asArray(event.related_titles).join(" ")}`.toLowerCase();
        if (search && !searchable.includes(search)) return false;
        return true;
      })
      .sort((left, right) => Number(right.total_score || 0) - Number(left.total_score || 0));
  }, [eventItems, filters.eventCategory, filters.eventSection, filters.eventSourceCount, filters.search]);

  const filteredItems = useMemo(() => {
    const search = filters.search.trim().toLowerCase();
    return items
      .filter((item) => {
      const score = scoreByNewsId.get(item.id);
      if (filters.source && item.source !== filters.source) return false;
      if (filters.sourceType && item.source_type !== filters.sourceType) return false;
      if (filters.freshness && item.freshness !== filters.freshness) return false;
      if (filters.availability && item.content_availability !== filters.availability) return false;
      if (filters.translationStatus && (item.translation_status || "skipped") !== filters.translationStatus) return false;
      if (filters.scoreView === "recommended" && !score?.recommended) return false;
      if (filters.category && score?.category !== filters.category) return false;
      if (filters.section && score?.recommended_section !== filters.section) return false;
      const searchableTitle = `${item.title_zh || ""} ${item.title || ""}`.toLowerCase();
      if (search && !searchableTitle.includes(search)) return false;
      return true;
    })
      .sort((left, right) => (scoreByNewsId.get(right.id)?.total_score || 0) - (scoreByNewsId.get(left.id)?.total_score || 0));
  }, [filters, items, scoreByNewsId]);
  const recommendedItems = useMemo(
    () => filteredItems.filter((item) => scoreByNewsId.get(item.id)?.recommended),
    [filteredItems, scoreByNewsId],
  );
  const visibleNewsItems = activeTab === "recommended" ? recommendedItems : filteredItems;

  const setFilter = (key: keyof NewsFilters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const toggleSource = (source: string) => {
    setSelectedSources((current) =>
      current.includes(source) ? current.filter((item) => item !== source) : [...current, source],
    );
  };

  const handleToggleNewsSelection = (item: NewsItem) => {
    setSelectionError("");
    setSavedSelection(null);
    setSelectedNewsIds((current) => {
      if (current.includes(item.id)) {
        const next = current.filter((newsId) => newsId !== item.id);
        setPrimaryNewsId((currentPrimary) => (currentPrimary === item.id ? next[0] || "" : currentPrimary));
        return next;
      }
      if (current.length >= MAX_SELECTED_NEWS) {
        setSelectionError(t.news.maxNewsSelection);
        flash(t.news.maxNewsSelection);
        return current;
      }
      if (!primaryNewsId) {
        setPrimaryNewsId(item.id);
      }
      return [...current, item.id];
    });
  };

  const handleRemoveNewsSelection = (newsId: string) => {
    setSelectionError("");
    setSavedSelection(null);
    setSelectedNewsIds((current) => {
      const next = current.filter((item) => item !== newsId);
      setPrimaryNewsId((currentPrimary) => (currentPrimary === newsId ? next[0] || "" : currentPrimary));
      return next;
    });
  };

  const handleSetPrimaryNews = (newsId: string) => {
    if (!selectedNewsIds.includes(newsId)) return;
    setPrimaryNewsId(newsId);
    setSavedSelection(null);
  };

  const handleClearNewsSelection = () => {
    setSelectedNewsIds([]);
    setPrimaryNewsId("");
    setSelectionError("");
    setSavedSelection(null);
  };

  const loadNewsDetail = async (newsId: string) => {
    if (!newsId) return;
    setSelectedNewsId(newsId);
    setDetailLoading(true);
    setDetailError("");
    try {
      const payload = await fetchNewsDetail(newsId);
      setNewsDetail(payload);
    } catch (err) {
      setNewsDetail(null);
      setDetailError(err instanceof Error ? err.message : t.news.detailLoadFailed);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleRefreshNewsDetail = async () => {
    if (!selectedNewsId) return;
    setDetailRefreshing(true);
    setDetailError("");
    try {
      const payload = await refreshNewsDetail(selectedNewsId);
      setNewsDetail(payload);
      setNews((current) => ({
        ...current,
        items: current.items.map((item) =>
          item.id === payload.news_id
            ? {
                ...item,
                content_availability: payload.content_availability || item.content_availability,
                content_text: payload.content_text || item.content_text,
              }
            : item,
        ),
      }));
      flash(t.news.detailRefreshSuccess);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : t.news.detailRefreshFailed);
    } finally {
      setDetailRefreshing(false);
    }
  };

  const handleCopyDetailText = async () => {
    const text = newsDetail?.content_text || newsDetail?.content_preview || newsDetail?.summary_zh || newsDetail?.summary || "";
    const copied = text ? await copyText(text) : false;
    flash(copied ? t.news.detailCopied : t.news.detailCopyFailed);
  };

  const handleCollect = async () => {
    setCollecting(true);
    setError("");
    const request: NewsCollectRequest = {
      hours,
      limit,
      include_fulltext: includeFulltext,
      translate,
      translate_limit: translateLimit,
      sources: selectedSources,
      keywords: normalizeKeywords(keywords),
    };
    try {
      const payload = await collectNews(request);
      setNews({
        ...emptyNewsResult(),
        ...payload,
        items: asArray(payload.items),
        warnings: asArray(payload.warnings),
        sources: asArray(payload.sources),
        source_counts: payload.source_counts || {},
        availability_counts: payload.availability_counts || {},
      });
      await refreshAll();
      flash(t.news.collectSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.news.collectFailed);
    } finally {
      setCollecting(false);
    }
  };

  const handleScoreNews = async () => {
    setScoring(true);
    setError("");
    try {
      const payload = await scoreNews({ top: scoreTop, min_score: minScore });
      setScores({
        ...emptyScoringResult(),
        ...payload,
        scores: asArray(payload.scores),
        warnings: asArray(payload.warnings),
        category_counts: payload.category_counts || {},
        section_counts: payload.section_counts || {},
      });
      await Promise.all([loadScoreReport(), loadEvents()]);
      flash(t.news.scoreSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.news.scoreFailed);
    } finally {
      setScoring(false);
    }
  };

  const handleBuildEvents = async () => {
    setBuildingEvents(true);
    setError("");
    try {
      const payload = await buildNewsEvents({
        top: eventTop,
        min_score: eventMinScore,
        similarity_threshold: similarityThreshold,
      });
      setEvents({
        ...emptyEventResult(),
        ...payload,
        events: asArray(payload.events),
        warnings: asArray(payload.warnings),
        category_counts: payload.category_counts || {},
        section_counts: payload.section_counts || {},
      });
      await loadEventReport();
      setActiveTab("events");
      flash(t.news.eventBuildSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.news.eventBuildFailed);
    } finally {
      setBuildingEvents(false);
    }
  };

  const handleWriteDigest = async () => {
    setWritingDigest(true);
    setError("");
    try {
      const payload = await writeNewsDigest({ top: digestTop });
      setDigest({
        ...emptyDigestArticle(),
        ...payload,
        sections: asArray(payload.sections),
        section_details: asArray(payload.section_details),
        source_event_ids: asArray(payload.source_event_ids),
        source_urls: asArray(payload.source_urls),
        warnings: asArray(payload.warnings),
        quality_notes: asArray(payload.quality_notes),
        quality_report: payload.quality_report || null,
      });
      setDigestReview(payload.quality_report || null);
      setDigestPackage("");
      setDigestPackagePath("");
      await loadDigest();
      setActiveTab("digest");
      flash(t.news.digestWriteSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.news.digestWriteFailed);
    } finally {
      setWritingDigest(false);
    }
  };

  const handleReviewDigest = async () => {
    setReviewingDigest(true);
    setError("");
    try {
      const payload = await reviewNewsDigest({ threshold: digestReviewThreshold, polish: digestPolish });
      setDigest({
        ...emptyDigestArticle(),
        ...payload,
        sections: asArray(payload.sections),
        section_details: asArray(payload.section_details),
        source_event_ids: asArray(payload.source_event_ids),
        source_urls: asArray(payload.source_urls),
        warnings: asArray(payload.warnings),
        quality_notes: asArray(payload.quality_notes),
        quality_report: payload.quality_report || null,
      });
      setDigestReview(payload.quality_report || null);
      await Promise.all([loadDigest(), loadDigestReview(), loadDigestPackage()]);
      setActiveTab("digest");
      flash(t.news.digestReviewSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.news.digestReviewFailed);
    } finally {
      setReviewingDigest(false);
    }
  };

  const handleCopyReport = async (content: string) => {
    const copied = content ? await copyText(content) : false;
    flash(copied ? t.news.reportCopied : t.news.reportCopyFailed);
  };

  const handleDownloadDigest = () => {
    if (!digest.content_markdown) {
      flash(t.news.reportCopyFailed);
      return;
    }
    downloadMarkdown(digest.title || "ai_news_digest", digest.content_markdown);
  };

  const handleDownloadDigestPackage = () => {
    if (!digestPackage) {
      flash(t.news.reportCopyFailed);
      return;
    }
    downloadMarkdown("packaged_ai_news_digest", digestPackage);
  };

  const handleSaveNewsSelection = async () => {
    if (!selectedNewsIds.length) {
      setSelectionError(t.news.selectAtLeastOneNews);
      return;
    }
    setSavingSelection(true);
    setSelectionError("");
    try {
      const payload = await createNewsSelection({
        news_ids: selectedNewsIds,
        primary_news_id: primaryNewsId || selectedNewsIds[0],
        direction_text: directionText,
      });
      setSavedSelection(payload);
      setPrimaryNewsId(payload.primary_news_id || primaryNewsId || selectedNewsIds[0]);
      flash(t.news.selectionSaved);
    } catch (err) {
      setSavedSelection(null);
      setSelectionError(err instanceof Error ? err.message : t.news.selectionSaveFailed);
    } finally {
      setSavingSelection(false);
    }
  };

  const handleGenerateArticlePlan = async () => {
    if (!selectedNewsIds.length && !savedSelection?.selection_id) {
      setSelectionError(t.news.saveSelectionFirst);
      flash(t.news.saveSelectionFirst);
      return;
    }
    setPlanningArticle(true);
    setSelectionError("");
    setError("");
    try {
      let selectionId = savedSelection?.selection_id || "";
      if (!selectionId) {
        const saved = await createNewsSelection({
          news_ids: selectedNewsIds,
          primary_news_id: primaryNewsId || selectedNewsIds[0],
          direction_text: directionText,
        });
        setSavedSelection(saved);
        setPrimaryNewsId(saved.primary_news_id || primaryNewsId || selectedNewsIds[0]);
        selectionId = saved.selection_id;
      }
      const payload = await createNewsArticlePlan({ selection_id: selectionId, use_latest: !selectionId });
      setArticlePlan({
        ...emptyArticlePlan(),
        ...payload,
        title_candidates: asArray(payload.title_candidates),
        key_facts: asArray(payload.key_facts),
        background_context: asArray(payload.background_context),
        why_it_matters: asArray(payload.why_it_matters),
        reader_takeaways: asArray(payload.reader_takeaways),
        developer_impact: asArray(payload.developer_impact),
        industry_impact: asArray(payload.industry_impact),
        article_structure: asArray(payload.article_structure),
        must_include: asArray(payload.must_include),
        should_avoid: asArray(payload.should_avoid),
        source_urls: asArray(payload.source_urls),
        factual_boundaries: asArray(payload.factual_boundaries),
        warnings: asArray(payload.warnings),
      });
      setActiveTab("articlePlan");
      flash(t.news.articlePlanGenerated);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.news.articlePlanFailed);
    } finally {
      setPlanningArticle(false);
    }
  };

  const handleCopyArticlePlanMarkdown = async () => {
    const content = articlePlan.plan_id ? articlePlanToMarkdown(articlePlan) : "";
    const copied = content ? await copyText(content) : false;
    flash(copied ? t.news.articlePlanCopied : t.news.reportCopyFailed);
  };

  const handleCopyArticlePlanJson = async () => {
    const content = articlePlan.plan_id ? JSON.stringify(articlePlan, null, 2) : "";
    const copied = content ? await copyText(content) : false;
    flash(copied ? t.news.articlePlanJsonCopied : t.news.reportCopyFailed);
  };

  return (
    <div className="page-stack ai-news-page">
      <section className="panel page-panel">
        <div className="panel-header page-header">
          <div>
            <h2>{t.news.latestTitle}</h2>
            <p>{t.news.latestSubtitle}</p>
          </div>
          {news.generated_at ? (
            <span className="soft-badge unknown">{`${t.news.generatedAt}: ${formatDate(news.generated_at)}`}</span>
          ) : null}
        </div>

        {loading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
        {error ? <div className="banner error">{error}</div> : null}
        {message ? <div className="banner success">{message}</div> : null}
        {news.warnings.length ? (
          <details className="banner warning news-warning">
            <summary>{`${t.news.partialSourceFailure} (${news.warnings.length})`}</summary>
            <ul>
              {news.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
        ) : null}

        <div className="news-overview-grid">
          <div className="news-stat">
            <span>{t.news.totalNews}</span>
            <strong>{news.total_count || items.length}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.freshNews}</span>
            <strong>{news.fresh_count || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.timeWindow}</span>
            <strong>{`${news.window_hours || 24}h`}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.sourceCount}</span>
            <strong>{news.sources.length || Object.keys(news.source_counts || {}).length}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.fullText}</span>
            <strong>{news.availability_counts.full_text || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.summaryOnly}</span>
            <strong>{news.availability_counts.summary_only || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.metadataOnly}</span>
            <strong>{news.availability_counts.metadata_only || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.latestDate}</span>
            <strong className="news-stat-date">{formatDate(latestDate)}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.translationSuccess}</span>
            <strong>{translatedCount}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.recommendedNews}</span>
            <strong>{scores.recommended_count || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.eventCard}</span>
            <strong>{events.event_count || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.recommendedEventCount}</span>
            <strong>{events.recommended_event_count || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.digestEventCount}</span>
            <strong>{digest.event_count || 0}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.generationMode}</span>
            <strong>{digest.content_markdown ? digest.generation_mode || "-" : "-"}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.articlePlan}</span>
            <strong>{articlePlan.plan_id ? articlePlan.generation_mode || "-" : "-"}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.topCategory}</span>
            <strong className="news-stat-date">{topCategory}</strong>
          </div>
          <div className="news-stat">
            <span>{t.news.averageScore}</span>
            <strong>{averageScore ? averageScore.toFixed(1) : "-"}</strong>
          </div>
        </div>
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.news.collectionControls}</h2>
          <button className="primary-button" type="button" onClick={handleCollect} disabled={collecting}>
            <RefreshCw className={collecting ? "spin-icon" : ""} size={17} aria-hidden="true" />
            <span>{collecting ? t.actions.collecting : t.actions.collectNow}</span>
          </button>
        </div>
        <div className="news-control-grid">
          <label>
            <span>{t.news.timeWindow}</span>
            <select value={hours} onChange={(event) => setHours(Number(event.target.value))}>
              <option value={24}>{t.news.past24h}</option>
              <option value={72}>{t.news.past72h}</option>
              <option value={168}>{t.news.past168h}</option>
            </select>
          </label>
          <label>
            <span>{t.news.limit}</span>
            <input type="number" min={1} max={500} value={limit} onChange={(event) => setLimit(Number(event.target.value) || 50)} />
          </label>
          <label className="checkbox-setting news-checkbox">
            <span>{t.news.includeFulltext}</span>
            <input type="checkbox" checked={includeFulltext} onChange={(event) => setIncludeFulltext(event.target.checked)} />
          </label>
          <label className="checkbox-setting news-checkbox">
            <span>{t.news.enableTranslation}</span>
            <input type="checkbox" checked={translate} onChange={(event) => setTranslate(event.target.checked)} />
          </label>
          <label>
            <span>{t.news.translationLimit}</span>
            <input type="number" min={0} max={500} value={translateLimit} onChange={(event) => setTranslateLimit(Number(event.target.value) || 0)} />
          </label>
          <label className="news-keywords-field">
            <span>{t.news.keywords}</span>
            <input value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder={t.news.keywordsPlaceholder} />
          </label>
        </div>
        <div className="news-source-picker" aria-label={t.news.sources}>
          <span>{t.news.sources}</span>
          <div>
            {SOURCE_OPTIONS.map((source) => (
              <label className="news-source-option" key={source}>
                <input type="checkbox" checked={selectedSources.includes(source)} onChange={() => toggleSource(source)} />
                <span>{source}</span>
              </label>
            ))}
          </div>
        </div>
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.news.scoringControls}</h2>
          <button className="primary-button" type="button" onClick={handleScoreNews} disabled={scoring || !items.length}>
            <Star className={scoring ? "spin-icon" : ""} size={17} aria-hidden="true" />
            <span>{scoring ? t.news.scoring : t.news.scoreNews}</span>
          </button>
        </div>
        <div className="news-control-grid">
          <label>
            <span>{t.news.recommendedLimit}</span>
            <input type="number" min={1} max={100} value={scoreTop} onChange={(event) => setScoreTop(Number(event.target.value) || 20)} />
          </label>
          <label>
            <span>{t.news.minScore}</span>
            <input type="number" min={0} max={100} value={minScore} onChange={(event) => setMinScore(Number(event.target.value) || 0)} />
          </label>
          <div className="news-score-status">
            <span>{t.news.scoringStatus}</span>
            <strong>{scores.generated_at ? t.news.scoringCompleted : t.news.notScored}</strong>
          </div>
          <div className="news-score-status">
            <span>{t.news.generatedAt}</span>
            <strong>{scores.generated_at ? formatDate(scores.generated_at) : "-"}</strong>
          </div>
        </div>
        {scores.warnings.length ? (
          <details className="banner warning news-warning">
            <summary>{`${t.labels.warnings} (${scores.warnings.length})`}</summary>
            <ul>
              {scores.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.news.eventBuildControls}</h2>
          <button className="primary-button" type="button" onClick={handleBuildEvents} disabled={buildingEvents || !scoreItems.length}>
            <RefreshCw className={buildingEvents ? "spin-icon" : ""} size={17} aria-hidden="true" />
            <span>{buildingEvents ? t.news.buildingEventCards : t.news.buildEventCards}</span>
          </button>
        </div>
        <div className="news-control-grid">
          <label>
            <span>{t.news.recommendedLimit}</span>
            <input type="number" min={1} max={100} value={eventTop} onChange={(event) => setEventTop(Number(event.target.value) || 20)} />
          </label>
          <label>
            <span>{t.news.minScore}</span>
            <input type="number" min={0} max={100} value={eventMinScore} onChange={(event) => setEventMinScore(Number(event.target.value) || 0)} />
          </label>
          <label>
            <span>{t.news.similarityThreshold}</span>
            <input
              type="number"
              min={0.35}
              max={0.9}
              step={0.01}
              value={similarityThreshold}
              onChange={(event) => setSimilarityThreshold(Number(event.target.value) || 0.55)}
            />
          </label>
          <div className="news-score-status">
            <span>{t.news.mergedEventCount}</span>
            <strong>{events.event_count || 0}</strong>
          </div>
          <div className="news-score-status">
            <span>{t.news.generatedAt}</span>
            <strong>{events.generated_at ? formatDate(events.generated_at) : "-"}</strong>
          </div>
        </div>
        {events.warnings.length ? (
          <details className="banner warning news-warning">
            <summary>{`${t.labels.warnings} (${events.warnings.length})`}</summary>
            <ul>
              {events.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.news.digestControls}</h2>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={handleReviewDigest} disabled={reviewingDigest || !digest.content_markdown}>
              <Sparkles className={reviewingDigest ? "spin-icon" : ""} size={17} aria-hidden="true" />
              <span>{reviewingDigest ? t.news.reviewingDigest : t.news.reviewDigest}</span>
            </button>
            <button className="primary-button" type="button" onClick={handleWriteDigest} disabled={writingDigest || !eventItems.length}>
              <RefreshCw className={writingDigest ? "spin-icon" : ""} size={17} aria-hidden="true" />
              <span>{writingDigest ? t.news.writingDigest : t.news.writeDigest}</span>
            </button>
          </div>
        </div>
        <div className="news-control-grid">
          <label>
            <span>{t.news.digestTop}</span>
            <input type="number" min={1} max={50} value={digestTop} onChange={(event) => setDigestTop(Number(event.target.value) || 12)} />
          </label>
          <label>
            <span>{t.news.publishThreshold}</span>
            <input
              type="number"
              min={0}
              max={100}
              value={digestReviewThreshold}
              onChange={(event) => setDigestReviewThreshold(Number(event.target.value) || 80)}
            />
          </label>
          <label className="checkbox-setting news-checkbox">
            <span>{t.news.polishDigest}</span>
            <input type="checkbox" checked={digestPolish} onChange={(event) => setDigestPolish(event.target.checked)} />
          </label>
          <div className="news-score-status">
            <span>{t.news.generationMode}</span>
            <strong>{digest.content_markdown ? digest.generation_mode || "-" : "-"}</strong>
          </div>
          <div className="news-score-status">
            <span>{t.news.digestEventCount}</span>
            <strong>{digest.event_count || 0}</strong>
          </div>
          <div className="news-score-status">
            <span>{t.news.generatedAt}</span>
            <strong>{digest.date || "-"}</strong>
          </div>
          <div className="news-score-status">
            <span>{t.news.qualityScore}</span>
            <strong>{digestReview?.total_score != null ? Number(digestReview.total_score).toFixed(1) : t.news.notReviewed}</strong>
          </div>
          <div className="news-score-status">
            <span>{t.news.publishStatus}</span>
            <strong>{digestReview ? (digestReview.publish_ready ? t.news.publishReady : t.news.needsRevision) : t.news.notReviewed}</strong>
          </div>
        </div>
        {digest.warnings.length ? (
          <details className="banner warning news-warning">
            <summary>{`${t.labels.warnings} (${digest.warnings.length})`}</summary>
            <ul>
              {digest.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.news.filters}</h2>
          <Filter size={18} aria-hidden="true" />
        </div>
        <div className="news-filter-grid">
          <label>
            <span>{t.news.source}</span>
            <select value={filters.source} onChange={(event) => setFilter("source", event.target.value)}>
              <option value="">{t.news.allSources}</option>
              {sourceOptions.map((source) => (
                <option value={source} key={source}>{source}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.sourceType}</span>
            <select value={filters.sourceType} onChange={(event) => setFilter("sourceType", event.target.value)}>
              <option value="">{t.news.allSources}</option>
              {sourceTypeOptions.map((sourceType) => (
                <option value={sourceType} key={sourceType}>{sourceType}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.freshness}</span>
            <select value={filters.freshness} onChange={(event) => setFilter("freshness", event.target.value)}>
              <option value="">{t.news.allSources}</option>
              {freshnessOptions.map((freshness) => (
                <option value={freshness} key={freshness}>{freshness}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.availability}</span>
            <select value={filters.availability} onChange={(event) => setFilter("availability", event.target.value)}>
              <option value="">{t.news.allSources}</option>
              {availabilityOptions.map((availability) => (
                <option value={availability} key={availability}>{availabilityLabel(availability, t)}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.translationStatus}</span>
            <select value={filters.translationStatus} onChange={(event) => setFilter("translationStatus", event.target.value)}>
              <option value="">{t.news.allSources}</option>
              {translationStatusOptions.map((status) => (
                <option value={status} key={status}>{translationStatusLabel(status, t)}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.recommendedNews}</span>
            <select value={filters.scoreView} onChange={(event) => setFilter("scoreView", event.target.value)}>
              <option value="all">{t.news.allNews}</option>
              <option value="recommended">{t.news.recommendedNews}</option>
            </select>
          </label>
          <label>
            <span>{t.news.category}</span>
            <select value={filters.category} onChange={(event) => setFilter("category", event.target.value)}>
              <option value="">{t.news.allCategories}</option>
              {categoryOptions.map((category) => (
                <option value={category} key={category}>{category}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.recommendedSection}</span>
            <select value={filters.section} onChange={(event) => setFilter("section", event.target.value)}>
              <option value="">{t.news.allSections}</option>
              {sectionOptions.map((section) => (
                <option value={section} key={section}>{section}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.eventCategory}</span>
            <select value={filters.eventCategory} onChange={(event) => setFilter("eventCategory", event.target.value)}>
              <option value="">{t.news.allCategories}</option>
              {eventCategoryOptions.map((category) => (
                <option value={category} key={category}>{category}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.eventSection}</span>
            <select value={filters.eventSection} onChange={(event) => setFilter("eventSection", event.target.value)}>
              <option value="">{t.news.allSections}</option>
              {eventSectionOptions.map((section) => (
                <option value={section} key={section}>{section}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.news.multiSourceEvent}</span>
            <select value={filters.eventSourceCount} onChange={(event) => setFilter("eventSourceCount", event.target.value)}>
              <option value="all">{t.news.allNews}</option>
              <option value="multi">{t.news.multiSourceEvent}</option>
            </select>
          </label>
          <label className="news-search-field">
            <span>{t.news.searchTitle}</span>
            <input value={filters.search} onChange={(event) => setFilter("search", event.target.value)} placeholder={t.news.searchPlaceholder} />
          </label>
        </div>
      </section>

      <div className="news-tabs" role="tablist" aria-label={t.news.aiNewsTabs}>
        {[
          ["list", t.news.newsList],
          ["recommended", t.news.recommendedNews],
          ["events", t.news.eventCard],
          ["articlePlan", t.news.articlePlan],
          ["digest", t.news.aiDigest],
          ["collectionReport", t.news.collectionReport],
          ["scoreReport", t.news.scoreReport],
          ["eventReport", t.news.eventReport],
        ].map(([tab, label]) => (
          <button
            className={activeTab === tab ? "active" : ""}
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab as NewsTab)}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === "list" || activeTab === "recommended" ? (
      <section className="news-list-detail-layout">
        <div className="panel page-panel news-list-panel">
          <div className="panel-header">
            <h2>{activeTab === "recommended" ? t.news.recommendedNews : t.news.newsList}</h2>
            <span className="soft-badge unknown">{`${visibleNewsItems.length}/${items.length}`}</span>
          </div>
          <div className="news-list">
            {!loading && !items.length ? <p className="empty-state">{t.news.noNews}</p> : null}
            {items.length && !visibleNewsItems.length ? <p className="empty-state">{t.news.noFilteredNews}</p> : null}
            {visibleNewsItems.map((item) => {
              const displayTitle = item.title_zh || item.title || "-";
              const displaySummary = item.summary_zh || item.summary || "";
              const hasOriginalTitle = item.title && item.title !== displayTitle;
              const score = scoreByNewsId.get(item.id);
              const isSelectedForWriting = selectedNewsIdSet.has(item.id);
              return (
                <article
                  className={`news-list-item ${selectedNewsId === item.id ? "selected" : ""} ${isSelectedForWriting ? "picked" : ""}`}
                  key={item.id || item.url}
                >
                  <label className="news-select-check">
                    <input
                      type="checkbox"
                      checked={isSelectedForWriting}
                      onChange={() => handleToggleNewsSelection(item)}
                      aria-label={`${t.news.selectNews}: ${displayTitle}`}
                    />
                    <span>{t.news.selectNews}</span>
                  </label>
                  <div className="news-item-main">
                    <div className="news-title-row">
                      <h3>{displayTitle}</h3>
                      <div className="news-title-badges">
                        {isSelectedForWriting && primaryNewsId === item.id ? <span className="soft-badge running">{t.news.primaryNews}</span> : null}
                        {score ? <span className={`news-score-pill ${score.recommended ? "recommended" : ""}`}>{score.total_score.toFixed(1)}</span> : null}
                      </div>
                    </div>
                    {hasOriginalTitle ? (
                      <p className="news-original-title">
                        <span>{t.news.originalTitle}: </span>
                        {item.title}
                      </p>
                    ) : null}
                    <div className="news-meta-row">
                      <span>{item.source || "-"}</span>
                      <span>{item.source_type || "-"}</span>
                      <span>{`${t.news.publishedAt}: ${formatDate(item.published_at)}`}</span>
                      <span>{`${t.news.fetchedAt}: ${formatDate(item.fetched_at)}`}</span>
                    </div>
                    <div className="news-badge-row">
                      <span className={`soft-badge ${item.freshness === "older" ? "pending" : "running"}`}>{item.freshness || "-"}</span>
                      <span className="soft-badge unknown">{availabilityLabel(item.content_availability, t)}</span>
                      <span className={`soft-badge ${item.translation_status === "failed" ? "failed" : "unknown"}`}>
                        {translationStatusLabel(item.translation_status, t)}
                      </span>
                      {score ? <span className="soft-badge unknown">{score.category}</span> : null}
                      {score ? <span className={`soft-badge ${score.recommended ? "running" : "pending"}`}>{score.recommended_section}</span> : null}
                      {item.language ? <span className="soft-badge unknown">{item.language}</span> : null}
                    </div>
                    {score?.reasons?.length ? (
                      <ul className="news-score-reasons">
                        {score.reasons.slice(0, 3).map((reason) => (
                          <li key={`${item.id}:${reason}`}>{reason}</li>
                        ))}
                      </ul>
                    ) : null}
                    {displaySummary ? <p className="news-summary">{displaySummary}</p> : null}
                    {item.translation_error ? <p className="news-translation-error">{item.translation_error}</p> : null}
                    {item.topics?.length || item.keywords?.length ? (
                      <div className="tag-list compact">
                        {[...asArray(item.topics), ...asArray(item.keywords)].slice(0, 8).map((tag) => (
                          <span className="soft-badge unknown" key={`${item.id}:${tag}`}>{tag}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <div className="news-item-actions">
                    <button
                      className="secondary-button news-original-link"
                      type="button"
                      onClick={() => void loadNewsDetail(item.id)}
                      disabled={detailLoading && selectedNewsId === item.id}
                    >
                      <ExternalLink size={16} aria-hidden="true" />
                      <span>{t.news.viewDetail}</span>
                    </button>
                    <a className="secondary-button news-original-link" href={item.url} target="_blank" rel="noreferrer">
                      <ExternalLink size={16} aria-hidden="true" />
                      <span>{t.actions.viewOriginal}</span>
                    </a>
                  </div>
                </article>
              );
            })}
          </div>
        </div>

        <aside className="news-side-column">
        <div className="panel page-panel news-selection-panel">
          <div className="panel-header compact-header">
            <div>
              <h2>{t.news.selectedNews}</h2>
              <p>{`${selectedNewsItems.length}/${MAX_SELECTED_NEWS}`}</p>
            </div>
            {savedSelection?.selection_id ? <span className="soft-badge running">{t.news.selectionSaved}</span> : null}
          </div>
          {selectionError ? <div className="banner error">{selectionError}</div> : null}
          {savedSelection?.selection_id ? (
            <p className="muted-line">{`${t.news.selectionSaved}: ${savedSelection.selection_id}`}</p>
          ) : null}
          <label className="news-direction-field">
            <span>{t.news.writingDirection}</span>
            <textarea
              value={directionText}
              onChange={(event) => {
                setDirectionText(event.target.value);
                setSavedSelection(null);
              }}
              placeholder={t.news.writingDirectionPlaceholder}
              rows={3}
            />
          </label>
          {selectedNewsItems.length ? (
            <div className="selected-news-list">
              {selectedNewsItems.map((item) => {
                const isPrimary = (primaryNewsId || selectedNewsIds[0]) === item.id;
                return (
                  <article className={`selected-news-item ${isPrimary ? "primary" : ""}`} key={`selected:${item.id}`}>
                    <div className="selected-news-title-row">
                      <h3>{item.title_zh || item.title || "-"}</h3>
                      <span className={`soft-badge ${isPrimary ? "running" : "unknown"}`}>
                        {isPrimary ? t.news.primaryNews : t.news.supportingSource}
                      </span>
                    </div>
                    <div className="news-meta-row">
                      <span>{item.source || "-"}</span>
                      <span>{item.source_type || "-"}</span>
                      <span>{availabilityLabel(item.content_availability, t)}</span>
                    </div>
                    <div className="selected-news-actions">
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => handleSetPrimaryNews(item.id)}
                        disabled={isPrimary}
                      >
                        <Check size={16} aria-hidden="true" />
                        <span>{t.news.setPrimaryNews}</span>
                      </button>
                      <button className="secondary-button" type="button" onClick={() => void loadNewsDetail(item.id)}>
                        <ExternalLink size={16} aria-hidden="true" />
                        <span>{t.news.viewDetail}</span>
                      </button>
                      <button className="secondary-button" type="button" onClick={() => handleRemoveNewsSelection(item.id)}>
                        <X size={16} aria-hidden="true" />
                        <span>{t.news.remove}</span>
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="empty-state">{t.news.selectAtLeastOneNews}</p>
          )}
          <div className="button-row selection-actions">
            <button className="secondary-button" type="button" onClick={handleClearNewsSelection} disabled={!selectedNewsIds.length}>
              <Trash2 size={16} aria-hidden="true" />
              <span>{t.news.clearSelection}</span>
            </button>
            <button className="primary-button" type="button" onClick={() => void handleSaveNewsSelection()} disabled={!selectedNewsIds.length || savingSelection}>
              <Save size={16} aria-hidden="true" />
              <span>{savingSelection ? t.actions.saving : t.news.saveSelection}</span>
            </button>
            <button className="primary-button" type="button" onClick={() => void handleGenerateArticlePlan()} disabled={planningArticle || !selectedNewsIds.length}>
              <Sparkles className={planningArticle ? "spin-icon" : ""} size={16} aria-hidden="true" />
              <span>{planningArticle ? t.news.articlePlanGenerating : t.news.generateArticlePlan}</span>
            </button>
          </div>
        </div>

        <div className="panel page-panel news-detail-panel">
          <div className="panel-header">
            <div>
              <h2>{t.news.newsDetail}</h2>
              {newsDetail?.news_id ? <p className="muted-line">{newsDetail.news_id}</p> : null}
            </div>
            <div className="button-row">
              <button className="secondary-button" type="button" onClick={handleRefreshNewsDetail} disabled={!selectedNewsId || detailRefreshing}>
                <RefreshCw className={detailRefreshing ? "spin-icon" : ""} size={16} aria-hidden="true" />
                <span>{t.news.refreshContent}</span>
              </button>
            </div>
          </div>
          {detailLoading ? <p className="empty-state">{t.messages.loadingData}</p> : null}
          {detailError ? <div className="banner error">{detailError}</div> : null}
          {!detailLoading && !newsDetail ? <p className="empty-state">{t.news.selectNewsDetail}</p> : null}
          {newsDetail ? (
            <div className="news-detail-content">
              <div>
                <h3>{newsDetail.title_zh || newsDetail.title || "-"}</h3>
                {newsDetail.title ? (
                  <p className="news-detail-original-title">
                    <span>{t.news.originalTitle}: </span>
                    {newsDetail.title}
                  </p>
                ) : null}
              </div>
              <div className="news-detail-meta">
                <span className="soft-badge unknown">{newsDetail.source || "-"}</span>
                <span className="soft-badge unknown">{newsDetail.source_type || "-"}</span>
                <span className="soft-badge unknown">{`${t.news.publishedAt}: ${formatDate(newsDetail.published_at)}`}</span>
                <span className="soft-badge unknown">{`${t.news.freshness}: ${newsDetail.freshness || "-"}`}</span>
                <span className="soft-badge unknown">{availabilityLabel(newsDetail.content_availability, t)}</span>
                <span className={`soft-badge ${newsDetail.extraction_status === "failed" ? "failed" : "running"}`}>
                  {`${t.news.contentFetchStatus}: ${extractionStatusLabel(newsDetail.extraction_status, t)}`}
                </span>
                <span className="soft-badge unknown">{`${t.labels.words}: ${newsDetail.word_count || 0}`}</span>
                {newsDetail.original_language ? <span className="soft-badge unknown">{newsDetail.original_language}</span> : null}
              </div>
              {newsDetail.content_availability !== "full_text" ? (
                <div className="banner warning news-detail-notice">
                  {newsDetail.summary || newsDetail.summary_zh ? t.news.summaryOnlyNotice : t.news.metadataOnlyNotice}
                  {newsDetail.extraction_error ? <span>{newsDetail.extraction_error}</span> : null}
                </div>
              ) : null}
              {newsDetail.summary_zh ? (
                <section className="news-detail-section">
                  <h4>{t.news.chineseSummary}</h4>
                  <p>{newsDetail.summary_zh}</p>
                </section>
              ) : null}
              {newsDetail.summary ? (
                <section className="news-detail-section">
                  <h4>{t.news.originalSummary}</h4>
                  <p>{newsDetail.summary}</p>
                </section>
              ) : null}
              <section className="news-detail-section">
                <h4>{t.news.contentPreview}</h4>
                {newsDetail.content_preview ? (
                  <pre className="news-content-preview">{newsDetail.content_preview}</pre>
                ) : (
                  <p className="empty-state">{t.news.metadataOnlyNotice}</p>
                )}
              </section>
              <div className="button-row">
                <button className="secondary-button" type="button" onClick={() => void handleCopyDetailText()} disabled={!newsDetail.content_preview && !newsDetail.content_text}>
                  <Clipboard size={16} aria-hidden="true" />
                  <span>{t.news.copyContent}</span>
                </button>
                <a className="secondary-button" href={newsDetail.url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} aria-hidden="true" />
                  <span>{t.news.openOriginal}</span>
                </a>
              </div>
            </div>
          ) : null}
        </div>
        </aside>
      </section>
      ) : null}

      {activeTab === "events" ? (
      <section className="panel page-panel">
        <div className="panel-header">
          <h2>{t.news.eventCard}</h2>
          <span className="soft-badge unknown">{`${filteredEvents.length}/${eventItems.length}`}</span>
        </div>
        <div className="news-list event-card-list">
          {!eventItems.length ? <p className="empty-state">{t.news.noEvents}</p> : null}
          {eventItems.length && !filteredEvents.length ? <p className="empty-state">{t.news.noFilteredNews}</p> : null}
          {filteredEvents.map((event) => {
            const displayTitle = event.event_title_zh || event.event_title || "-";
            const displaySummary = event.event_summary_zh || event.event_summary || "";
            return (
              <article className="news-list-item event-card" key={event.event_id || event.primary_url}>
                <div className="news-item-main">
                  <div className="news-title-row">
                    <h3>{displayTitle}</h3>
                    <span className={`news-score-pill ${event.recommended_section !== "暂不推荐" ? "recommended" : ""}`}>
                      {Number(event.total_score || 0).toFixed(1)}
                    </span>
                  </div>
                  <div className="news-meta-row">
                    <span>{`${t.news.recommendedSection}: ${event.recommended_section || "-"}`}</span>
                    <span>{`${t.news.sourceCount}: ${event.source_count || 0}`}</span>
                    <span>{`${t.news.primarySource}: ${event.primary_source || "-"}`}</span>
                    <span>{`${t.news.freshness}: ${event.freshness || "-"}`}</span>
                  </div>
                  <div className="news-badge-row">
                    <span className="soft-badge running">{event.category || "-"}</span>
                    <span className="soft-badge unknown">{availabilityLabel(event.content_availability, t)}</span>
                    {asArray(event.source_types).slice(0, 5).map((sourceType) => (
                      <span className="soft-badge unknown" key={`${event.event_id}:${sourceType}`}>{sourceType}</span>
                    ))}
                  </div>
                  {displaySummary ? <p className="news-summary">{displaySummary}</p> : null}
                  {asArray(event.sources).length ? (
                    <p className="news-original-title">
                      <span>{t.news.sources}: </span>
                      {asArray(event.sources).join(", ")}
                    </p>
                  ) : null}
                  {asArray(event.related_titles).length ? (
                    <div>
                      <p className="news-original-title"><span>{t.news.relatedNews}: </span></p>
                      <ul className="news-score-reasons">
                        {asArray(event.related_titles).slice(0, 5).map((title) => (
                          <li key={`${event.event_id}:${title}`}>{title}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {asArray(event.reasons).length ? (
                    <ul className="news-score-reasons">
                      {asArray(event.reasons).slice(0, 3).map((reason) => (
                        <li key={`${event.event_id}:${reason}`}>{reason}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
                <a className="secondary-button news-original-link" href={event.primary_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} aria-hidden="true" />
                  <span>{t.actions.viewOriginal}</span>
                </a>
              </article>
            );
          })}
        </div>
      </section>
      ) : null}

      {activeTab === "articlePlan" ? (
      <section className="panel page-panel news-article-plan-panel">
        <div className="panel-header">
          <div>
            <h2>{t.news.articlePlan}</h2>
            {articlePlan.plan_id ? <p className="muted-line">{articlePlan.plan_id}</p> : null}
          </div>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={() => void handleCopyArticlePlanMarkdown()} disabled={!articlePlan.plan_id}>
              <Clipboard size={16} aria-hidden="true" />
              <span>{t.news.copyArticlePlanMarkdown}</span>
            </button>
            <button className="secondary-button" type="button" onClick={() => void handleCopyArticlePlanJson()} disabled={!articlePlan.plan_id}>
              <Clipboard size={16} aria-hidden="true" />
              <span>{t.news.copyArticlePlanJson}</span>
            </button>
          </div>
        </div>
        {articlePlan.plan_id ? (
          <>
            <div className="news-digest-meta">
              <span className="soft-badge unknown">{`${t.news.generationMode}: ${articlePlan.generation_mode || "-"}`}</span>
              <span className="soft-badge unknown">{`${t.news.generatedAt}: ${formatDate(articlePlan.generated_at)}`}</span>
              <span className="soft-badge running">{`${t.news.primaryNews}: ${articlePlan.primary_news_id || "-"}`}</span>
              <span className="soft-badge unknown">{`${t.news.selectionSaved}: ${articlePlan.selection_id || "-"}`}</span>
            </div>
            {asArray(articlePlan.warnings).length ? (
              <details className="banner warning news-warning article-plan-warning" open>
                <summary>{`${t.labels.warnings} (${asArray(articlePlan.warnings).length})`}</summary>
                <ul>
                  {asArray(articlePlan.warnings).map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            <div className="article-plan-hero">
              <div>
                <span>{t.news.recommendedTitle}</span>
                <h3>{articlePlan.recommended_title || "-"}</h3>
              </div>
              <div>
                <span>{t.news.coreAngle}</span>
                <p>{articlePlan.core_angle || "-"}</p>
              </div>
              <div>
                <span>{t.news.leadHook}</span>
                <p>{articlePlan.lead_hook || "-"}</p>
              </div>
              <div>
                <span>{t.news.eventSummary}</span>
                <p>{articlePlan.event_summary || "-"}</p>
              </div>
            </div>
            <div className="article-plan-grid">
              {[
                [t.news.titleCandidates, articlePlan.title_candidates],
                [t.news.keyFacts, articlePlan.key_facts],
                [t.news.backgroundContext, articlePlan.background_context],
                [t.news.whyItMatters, articlePlan.why_it_matters],
                [t.news.readerTakeaways, articlePlan.reader_takeaways],
                [t.news.developerImpact, articlePlan.developer_impact],
                [t.news.industryImpact, articlePlan.industry_impact],
                [t.news.articleStructure, articlePlan.article_structure],
                [t.news.mustInclude, articlePlan.must_include],
                [t.news.shouldAvoid, articlePlan.should_avoid],
                [t.news.factualBoundaries, articlePlan.factual_boundaries],
              ].map(([title, values]) => (
                <section className="article-plan-section" key={String(title)}>
                  <h3>{String(title)}</h3>
                  {asArray(values as string[]).length ? (
                    <ul>
                      {asArray(values as string[]).map((value) => (
                        <li key={`${title}:${value}`}>{value}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="empty-state">{t.empty.noData}</p>
                  )}
                </section>
              ))}
              <section className="article-plan-section">
                <h3>{t.news.writingStyle}</h3>
                <p>{articlePlan.writing_style || "-"}</p>
              </section>
              <section className="article-plan-section source-links">
                <h3>{t.news.sourceUrls}</h3>
                {asArray(articlePlan.source_urls).length ? (
                  <ul>
                    {asArray(articlePlan.source_urls).map((url) => (
                      <li key={url}>
                        <a href={url} target="_blank" rel="noreferrer">{url}</a>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="empty-state">{t.empty.noData}</p>
                )}
              </section>
            </div>
          </>
        ) : (
          <p className="empty-state">{t.news.noArticlePlan}</p>
        )}
      </section>
      ) : null}

      {activeTab === "digest" ? (
      <section className="panel page-panel">
        <div className="panel-header">
          <div>
            <h2>{t.news.aiDigest}</h2>
            {digestPath ? <p className="muted-line">{digestPath}</p> : null}
          </div>
          <div className="button-row">
            <button className="secondary-button" type="button" onClick={() => void handleCopyReport(digest.content_markdown)} disabled={!digest.content_markdown}>
              <Clipboard size={16} aria-hidden="true" />
              <span>{t.actions.copyMarkdown}</span>
            </button>
            <button className="secondary-button" type="button" onClick={handleDownloadDigest} disabled={!digest.content_markdown}>
              <Download size={16} aria-hidden="true" />
              <span>{t.actions.downloadMarkdown}</span>
            </button>
          </div>
        </div>
        {digest.content_markdown ? (
          <>
            <div className="news-digest-meta">
              <span className="soft-badge unknown">{`${t.news.generationMode}: ${digest.generation_mode || "-"}`}</span>
              <span className="soft-badge unknown">{`${t.news.digestEventCount}: ${digest.event_count || 0}`}</span>
              <span className="soft-badge unknown">{`${t.labels.words}: ${digest.word_count || 0}`}</span>
              {asArray(digest.sections).map((section) => (
                <span className="soft-badge running" key={section}>{section}</span>
              ))}
            </div>
            {asArray(digest.quality_notes).length ? (
              <ul className="news-score-reasons">
                {asArray(digest.quality_notes).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
            <div className="news-digest-quality-grid">
              <div className="news-quality-summary">
                <span>{t.news.qualityScore}</span>
                <strong>{digestReview?.total_score != null ? Number(digestReview.total_score).toFixed(1) : t.news.notReviewed}</strong>
                <em>{digestReview ? (digestReview.publish_ready ? t.news.publishReady : t.news.needsRevision) : t.news.notReviewed}</em>
              </div>
              {digestReview ? (
                <div className="news-quality-detail">
                  <p>{digestReview.summary || ""}</p>
                  {asArray(digestReview.issues).length ? (
                    <>
                      <h3>{t.news.majorIssues}</h3>
                      <ul className="news-score-reasons">
                        {asArray(digestReview.issues).slice(0, 5).map((issue) => (
                          <li key={`${issue.issue_type}:${issue.description}`}>
                            <strong>{`[${issue.severity || "-"}] ${issue.issue_type || "-"}`}</strong>
                            {`: ${issue.description || ""}`}
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p className="muted-line">{t.news.noMajorIssues}</p>
                  )}
                  {asArray(digestReview.rewrite_recommendations).length ? (
                    <>
                      <h3>{t.news.rewriteRecommendations}</h3>
                      <ul className="news-score-reasons">
                        {asArray(digestReview.rewrite_recommendations).slice(0, 5).map((recommendation) => (
                          <li key={recommendation}>{recommendation}</li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </div>
              ) : (
                <p className="empty-state">{t.news.noDigestReview}</p>
              )}
            </div>
            <div className="news-package-panel">
              <div className="panel-header compact-header">
                <div>
                  <h3>{t.news.packagePreview}</h3>
                  {digestPackagePath || digest.package_path ? <p className="muted-line">{digestPackagePath || digest.package_path}</p> : null}
                </div>
                <div className="button-row">
                  <button className="secondary-button" type="button" onClick={() => void handleCopyReport(digestPackage)} disabled={!digestPackage}>
                    <Clipboard size={16} aria-hidden="true" />
                    <span>{t.news.copyPackage}</span>
                  </button>
                  <button className="secondary-button" type="button" onClick={handleDownloadDigestPackage} disabled={!digestPackage}>
                    <Download size={16} aria-hidden="true" />
                    <span>{t.news.downloadPackage}</span>
                  </button>
                </div>
              </div>
              {digestPackage ? (
                <pre className="prompt-block news-report-preview">{digestPackage}</pre>
              ) : (
                <p className="empty-state">{digestReview ? t.news.noDigestPackage : t.news.reviewFirstForPackage}</p>
              )}
            </div>
            <pre className="prompt-block news-report-preview">{digest.content_markdown}</pre>
          </>
        ) : (
          <p className="empty-state">{t.news.noDigest}</p>
        )}
      </section>
      ) : null}

      {activeTab === "collectionReport" ? (
      <section className="panel page-panel">
        <div className="panel-header">
          <div>
            <h2>{t.news.collectionReport}</h2>
            {reportPath ? <p className="muted-line">{reportPath}</p> : null}
          </div>
          <button className="secondary-button" type="button" onClick={() => void handleCopyReport(report)} disabled={!report}>
            <Clipboard size={16} aria-hidden="true" />
            <span>{t.actions.copyReport}</span>
          </button>
        </div>
        {reportError ? <div className="banner error">{reportError}</div> : null}
        {report ? (
          <pre className="prompt-block news-report-preview">{report}</pre>
        ) : (
          <p className="empty-state">{t.news.noReport}</p>
        )}
      </section>
      ) : null}

      {activeTab === "scoreReport" ? (
      <section className="panel page-panel">
        <div className="panel-header">
          <div>
            <h2>{t.news.scoreReport}</h2>
            {scoreReportPath ? <p className="muted-line">{scoreReportPath}</p> : null}
          </div>
          <button className="secondary-button" type="button" onClick={() => void handleCopyReport(scoreReport)} disabled={!scoreReport}>
            <Clipboard size={16} aria-hidden="true" />
            <span>{t.actions.copyReport}</span>
          </button>
        </div>
        {reportError ? <div className="banner error">{reportError}</div> : null}
        {scoreReport ? (
          <pre className="prompt-block news-report-preview">{scoreReport}</pre>
        ) : (
          <p className="empty-state">{t.news.noScoreReport}</p>
        )}
      </section>
      ) : null}

      {activeTab === "eventReport" ? (
      <section className="panel page-panel">
        <div className="panel-header">
          <div>
            <h2>{t.news.eventReport}</h2>
            {eventReportPath ? <p className="muted-line">{eventReportPath}</p> : null}
          </div>
          <button className="secondary-button" type="button" onClick={() => void handleCopyReport(eventReport)} disabled={!eventReport}>
            <Clipboard size={16} aria-hidden="true" />
            <span>{t.actions.copyReport}</span>
          </button>
        </div>
        {reportError ? <div className="banner error">{reportError}</div> : null}
        {eventReport ? (
          <pre className="prompt-block news-report-preview">{eventReport}</pre>
        ) : (
          <p className="empty-state">{t.news.noEventReport}</p>
        )}
      </section>
      ) : null}
    </div>
  );
}
