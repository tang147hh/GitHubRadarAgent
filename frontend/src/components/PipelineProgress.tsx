import { Check, Circle, LoaderCircle, X } from "lucide-react";
import type { Translation } from "../i18n";
import type { PipelineStage, RunInfo } from "../types";

type PipelineProgressProps = {
  t: Translation;
  stages: PipelineStage[];
  runInfo?: RunInfo;
  currentStage?: string | null;
};

type PipelineTone = "success" | "failed" | "running" | "pending";

const stageLabelKey = (name = "") => {
  if (name === "select-projects") return "selectProjects";
  if (name === "research-selected") return "researchSelected";
  if (name === "plan-content") return "contentPlan";
  if (name === "write-articles") return "write";
  if (name === "review-articles") return "review";
  return name;
};

const statusTone = (status = ""): PipelineTone => {
  const normalized = status.toLowerCase();
  if (["success", "completed", "complete", "done"].includes(normalized)) return "success";
  if (["failed", "error"].includes(normalized)) return "failed";
  if (["running", "in_progress"].includes(normalized)) return "running";
  if (["pending", "queued", "waiting"].includes(normalized)) return "pending";
  return "pending";
};

export function PipelineProgress({ t, stages, runInfo, currentStage }: PipelineProgressProps) {
  const visibleStages = stages.length ? stages : [];
  const overallTone = statusTone(runInfo?.status || visibleStages.find((stage) => statusTone(stage.status) === "failed")?.status);

  return (
    <section className="panel pipeline-panel">
      <div className="panel-header">
        <h2>{t.sections.pipeline}</h2>
        <span className={`soft-badge ${overallTone}`}>{t.statusLabels[overallTone]}</span>
      </div>

      <div className="pipeline-track">
        {visibleStages.map((stage, index) => {
          const tone = statusTone(stage.status);
          const Icon = tone === "success" ? Check : tone === "failed" ? X : tone === "running" ? LoaderCircle : Circle;
          const labelKey = stageLabelKey(stage.name);
          const label = labelKey in t.pipeline ? t.pipeline[labelKey as keyof typeof t.pipeline] : stage.name || t.status.unknown;
          const isCurrent = Boolean(currentStage && stage.name === currentStage);

          return (
          <div className={`pipeline-step ${tone}${isCurrent ? " current" : ""}`} key={`${stage.name}-${index}`}>
            <div className={`step-node ${tone}`}>
              <Icon className={tone === "running" ? "spin-icon" : ""} size={16} aria-hidden="true" />
            </div>
            {index < visibleStages.length - 1 ? <div className={`step-line ${tone}`} /> : null}
            <span>{label}</span>
            <small title={stage.error || stage.message || ""}>{t.statusLabels[tone]}</small>
          </div>
          );
        })}
      </div>

      <div className="run-info-grid">
        <div>
          <span>{t.labels.runId}</span>
          <strong>{runInfo?.run_id || t.empty.noData}</strong>
        </div>
        <div>
          <span>{t.labels.status}</span>
          <strong className={`${statusTone(runInfo?.status || "")}-text`}>{runInfo?.status || t.status.unknown}</strong>
        </div>
        <div>
          <span>{t.labels.duration}</span>
          <strong>{runInfo?.duration || t.empty.noData}</strong>
        </div>
        <div>
          <span>{t.labels.output}</span>
          <strong>{runInfo?.output || t.empty.noData}</strong>
        </div>
      </div>
    </section>
  );
}
