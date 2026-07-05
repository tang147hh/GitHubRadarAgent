import type { Language } from "../i18n";

export const stats = {
  todayCandidates: 12,
  topScoredProjects: 5,
  finalArticles: 2,
  reviewPassRate: "100%",
};

export const pipelineStages = ["discover", "score", "research", "angles", "write", "review"] as const;

export const runInfo = {
  runId: "daily_20260701_161006",
  status: "success",
  duration: "3m 42s",
  output: "outputs/2026-07-01/",
};

export const scoreRanking = [
  {
    rank: 1,
    project: "langgenius/dify",
    stars: "147k",
    score: 94.5,
    language: "TypeScript",
    status: "selected",
  },
  {
    rank: 2,
    project: "langchain-ai/langchain",
    stars: "140k",
    score: 94.5,
    language: "Python",
    status: "selected",
  },
  {
    rank: 3,
    project: "affaan-m/ECC",
    stars: "224k",
    score: 94.0,
    language: "Python",
    status: "selected",
  },
];

export const finalArticles = [
  {
    title: {
      zh: "GitHub 上这个 dify，把 Agent 工作流开发做成了开源项目",
      en: "This GitHub project turns Agent workflow development into an open-source platform",
    },
    project: "langgenius/dify",
    words: 1974,
    reviewScore: 89,
  },
  {
    title: {
      zh: "GitHub 上这个 langchain，把 Agent 工程开发做成了开源项目",
      en: "This GitHub project brings Agent engineering into an open-source framework",
    },
    project: "langchain-ai/langchain",
    words: 1860,
    reviewScore: 91,
  },
];

export const articlePreview = {
  title: {
    zh: "GitHub 上这个 dify，把 Agent 工作流开发做成了开源项目",
    en: "This GitHub project turns Agent workflow development into an open-source platform",
  },
  intro: {
    zh: "Dify 是一个开源的 LLM 应用开发平台，专注于 Agent 工作流编排与可视化开发，让你更快构建、测试与发布 AI 应用。",
    en: "Dify is an open-source LLM application development platform focused on Agent workflow orchestration and visual development, helping teams build, test, and ship AI apps faster.",
  },
  markdown: {
    zh: "## 核心亮点\n- 可视化 Workflow：拖拽式编排，降低 Agent 工作流开发门槛\n- 丰富的插件生态：支持多种模型、工具与数据源接入\n- 开箱即用：一键部署，支持本地与云端环境\n- 开放可扩展：插件机制与 API 完善，便于二次开发\n\n> Dify 的目标是让每个人都能轻松构建生产级的 AI 应用，而不仅仅是展示工程。",
    en: "## Key Highlights\n- Visual Workflow: drag-and-drop orchestration lowers the barrier to Agent workflow development\n- Rich Plugin Ecosystem: supports multiple models, tools, and data sources\n- Ready to Use: one-click deployment for local and cloud environments\n- Open and Extensible: plugin mechanisms and APIs support secondary development\n\n> Dify aims to make production-grade AI applications easier to build, not just easier to demo.",
  },
  projectUrl: "https://github.com/langgenius/dify",
};

export const reviewSummary = {
  scores: [
    { key: "factual_score", value: 28, max: 30 },
    { key: "title_score", value: 18, max: 20 },
    { key: "structure_score", value: 18, max: 20 },
    { key: "readability_score", value: 13, max: 15 },
    { key: "completeness_score", value: 14, max: 15 },
  ],
  factualWarnings: {
    zh: [
      "第 3 段提到“支持所有主流模型”，建议改成“支持多种主流模型”。",
      "第 5 段关于性能数据缺少来源，建议补充引用官方基准。",
    ],
    en: [
      "Paragraph 3 says it supports all mainstream models. Prefer: supports multiple mainstream models.",
      "Paragraph 5 mentions performance data without a source. Add an official benchmark reference.",
    ],
  },
  sourceLinks: [
    "https://github.com/langgenius/dify",
    "https://docs.dify.ai/",
    "https://github.com/langgenius/dify/releases",
  ],
};

export const getLocalized = <T>(value: Record<Language, T>, language: Language): T => value[language];
