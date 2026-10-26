import { useEffect, useRef, useState } from "react";
import type { RoutePoint } from "../types";

type LatLng = {lat: number; lng: number};
type GoogleApi = { maps: {
  Map: new (element: HTMLElement, options: object) => {fitBounds: (bounds: object) => void; addListener: (name: string, fn: (event: {latLng?: {lat: () => number; lng: () => number}}) => void) => {remove: () => void}};
  LatLngBounds: new () => {extend: (point: LatLng) => void};
  Polyline: new (options: object) => {setMap: (map: unknown) => void};
  marker: { AdvancedMarkerElement: new (options: object) => {map: unknown} };
}};
let googlePromise: Promise<GoogleApi> | undefined;
function loadMaps(key: string): Promise<GoogleApi> {
  const target = window as unknown as {google?: GoogleApi; agroMapsReady?: () => void};
  if (target.google?.maps.marker) return Promise.resolve(target.google);
  if (!googlePromise) googlePromise = new Promise((resolve, reject) => {
    target.agroMapsReady = () => target.google ? resolve(target.google) : reject(new Error("No se pudo abrir Google Maps"));
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&libraries=marker&loading=async&callback=agroMapsReady&language=es&region=AR`;
    script.async = true;
    script.onerror = () => { googlePromise = undefined; reject(new Error("No se pudo cargar Google Maps")); };
    document.head.appendChild(script);
  });
  return googlePromise;
}

export function decodePolyline(encoded: string): LatLng[] {
  let index = 0, lat = 0, lng = 0;
  const points: LatLng[] = [];
  const read = () => {
    let result = 0, shift = 0, byte: number;
    do {
      if (index >= encoded.length || shift > 30) throw new Error("Trazado inválido");
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 31) << shift; shift += 5;
    } while (byte >= 32);
    return result & 1 ? ~(result >> 1) : result >> 1;
  };
  while (index < encoded.length) { lat += read(); lng += read(); points.push({lat:lat / 1e5, lng:lng / 1e5}); }
  return points;
}

export function GoogleRouteMap({apiKey, points, polyline, latest, onSelect}: {apiKey: string | null; points: RoutePoint[]; polyline?: string; latest?: LatLng; onSelect?: (point: LatLng) => void}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!apiKey || !ref.current) return;
    let disposed = false;
    let cleanup = () => {};
    loadMaps(apiKey).then((g) => {
      if (disposed || !ref.current) return;
      const map = new g.maps.Map(ref.current, {zoom:6, center:{lat:-34.6,lng:-58.4}, mapId:"DEMO_MAP_ID", streetViewControl:false});
      const bounds = new g.maps.LatLngBounds();
      const markers: {map: unknown}[] = [];
      points.forEach((p,i) => {
        if (p.latitude === null || p.longitude === null) return;
        const position = {lat:p.latitude,lng:p.longitude}; bounds.extend(position);
        const content = document.createElement("span"); content.className = "map-point-label"; content.textContent = i === 0 ? "A" : i === points.length - 1 ? "B" : String(i);
        markers.push(new g.maps.marker.AdvancedMarkerElement({map, position, title:p.label, content}));
      });
      if (latest) {
        bounds.extend(latest);
        const content = document.createElement("span"); content.className = "map-truck-label"; content.textContent = "🚚";
        markers.push(new g.maps.marker.AdvancedMarkerElement({map, position:latest, title:"Última ubicación informada", content}));
      }
      const line = polyline ? new g.maps.Polyline({map, path:decodePolyline(polyline), strokeColor:"#166534", strokeWeight:4}) : undefined;
      if (points.some(p => p.latitude !== null) || latest) map.fitBounds(bounds);
      const listener = map.addListener("click", (event) => { if (event.latLng && onSelect) onSelect({lat:event.latLng.lat(),lng:event.latLng.lng()}); });
      cleanup = () => {listener.remove(); line?.setMap(null); markers.forEach(marker => {marker.map = null;});};
    }).catch((reason: Error) => { if (!disposed) setError(reason.message); });
    return () => {disposed = true; cleanup();};
  }, [apiKey, points, polyline, latest, onSelect]);
  if (!apiKey) return <p className="state-box">El mapa está pendiente de configurar Google Maps. Las ubicaciones y controles siguen disponibles.</p>;
  return <>{error ? <p role="alert">{error}</p> : null}<div ref={ref} className="google-route-map" aria-label="Recorrido estimado y última posición informada del camión" /></>;
}
