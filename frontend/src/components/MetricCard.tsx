import { Link } from "react-router-dom";
import { Icon } from "./Icon";

type MetricCardProps = {
  label: string;
  value: number | string;
  hint?: string;
  to?: string;
  icon?: string;
};

export function MetricCard({ label, value, hint, to, icon = "box" }: MetricCardProps) {
  const content = <><span className="metric-card-heading"><Icon name={icon} />{label}</span><strong>{value}</strong>{hint ? <small>{hint}</small> : to ? <small>Ver registros →</small> : null}</>;
  return to ? <Link className="metric-card metric-card-link" to={to}>{content}</Link> : <article className="metric-card">{content}</article>;
}
