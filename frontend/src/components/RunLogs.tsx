import { TerminalSquare } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Translation } from "../i18n";
import type { JobLog } from "../types";

type RunLogsProps = {
  t: Translation;
  logs: JobLog[];
  activeJobId?: string | null;
};

function formatLogTime(value?: string) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function RunLogs({ t, logs, activeJobId }: RunLogsProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = scrollRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }, [logs]);

  return (
    <section className="panel run-logs-panel">
      <div className="panel-header">
        <h2>{t.sections.runLogs}</h2>
        <span className="soft-badge unknown">
          <TerminalSquare size={14} aria-hidden="true" />
          {activeJobId ? activeJobId.slice(0, 8) : t.empty.noData}
        </span>
      </div>

      <div className="run-log-list" ref={scrollRef}>
        {logs.length ? (
          logs.map((log, index) => (
            <div className="run-log-row" key={`${log.time || "log"}-${index}`}>
              <time>{formatLogTime(log.time)}</time>
              <span className="run-log-stage">{log.stage || log.type || "-"}</span>
              <p>{log.message || "-"}</p>
            </div>
          ))
        ) : (
          <p className="empty-state">{t.empty.noLogs}</p>
        )}
      </div>
    </section>
  );
}
