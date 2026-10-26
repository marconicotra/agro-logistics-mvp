import { StatusBadge } from "./StatusBadge";
import { display } from "../format";

type RouteMapCardProps = {
  origin: string | null;
  destination: string | null;
  status: string | null;
  eyebrow?: string;
};

export function RouteMapCard({ origin, destination, status, eyebrow }: RouteMapCardProps) {
  return (
    <div className="route-map-card">
      <div className="route-map-header">
        <div>
          {eyebrow ? <span className="route-map-eyebrow">{eyebrow}</span> : null}
          <strong>Ruta operativa</strong>
        </div>
        {status ? <StatusBadge status={status} /> : null}
      </div>
      <div className="route-track">
        <div className="route-stop">
          <span className="route-dot origin" />
          <div>
            <small>Origen</small>
            <strong>{display(origin)}</strong>
          </div>
        </div>
        <div className="route-line" />
        <div className="route-stop">
          <span className="route-dot destination" />
          <div>
            <small>Destino</small>
            <strong>{display(destination)}</strong>
          </div>
        </div>
      </div>
    </div>
  );
}
