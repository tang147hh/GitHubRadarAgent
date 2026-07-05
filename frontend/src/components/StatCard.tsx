import type { LucideIcon } from "lucide-react";

type StatCardProps = {
  label: string;
  value: string | number;
  icon: LucideIcon;
  tone: "blue" | "green" | "amber" | "violet";
};

export function StatCard({ label, value, icon: Icon, tone }: StatCardProps) {
  return (
    <section className="stat-card">
      <div className={`stat-icon ${tone}`}>
        <Icon size={22} aria-hidden="true" />
      </div>
      <div className="stat-copy">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </section>
  );
}
