import { statusLabel } from "../labels";

type StatusBadgeProps = {
  status?: string | null;
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const value = status || "-";
  const normalized = value.toLowerCase().replace(/_/g, "-");
  return <span className={`status-badge status-${normalized}`}>{statusLabel(value)}</span>;
}
