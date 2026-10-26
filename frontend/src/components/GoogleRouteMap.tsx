import { useEffect, useRef, useState } from "react";
import type { RoutePoint } from "../types";

type LatLng = {lat: number; lng: number};
type GoogleLatLng = {lat: () => number; lng: () => number};
type MapPosition = LatLng | GoogleLatLng;
type MapEvent = {latLng?: GoogleLatLng};
type MapMarker = {
  map: unknown;
  position?: MapPosition;
  addListener: (name: string, fn: (event: MapEvent) => void) => {remove: () => void};
};
type GoogleMap = {
  fitBounds: (bounds: object, padding?: number) => void;
  panTo: (point: LatLng) => void;
  setZoom: (zoom: number) => void;
  setOptions: (options: object) => void;
  addListener: (name: string, fn: (event: MapEvent) => void) => {remove: () => void};
};
type GoogleApi = { maps: {
  Map: new (element: HTMLElement, options: object) => GoogleMap;
  LatLngBounds: new () => {extend: (point: LatLng) => void};
  Polyline: new (options: object) => {setMap: (map: unknown) => void};
  marker: { AdvancedMarkerElement: new (options: object) => MapMarker };
}};

let googlePromise: Promise<GoogleApi> | undefined;
function plainPoint(position: MapPosition | undefined): LatLng | null {
  if (!position) return null;
  return {
    lat: typeof position.lat === "function" ? position.lat() : position.lat,
    lng: typeof position.lng === "function" ? position.lng() : position.lng,
  };
}

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
  while (index < encoded.length) { lat += read(); lng += read(); points.push({lat:lat / 1e5,lng:lng / 1e5}); }
  return points;
}

type Selection = {active: boolean; point: LatLng | null};
export function GoogleRouteMap({apiKey, points, polyline, latest, selection, onSelect}: {
  apiKey: string | null;
  points: RoutePoint[];
  polyline?: string;
  latest?: LatLng;
  selection?: Selection;
  onSelect?: (point: LatLng) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<GoogleMap | null>(null);
  const googleRef = useRef<GoogleApi | null>(null);
  const overlaysRef = useRef<Array<{map: unknown} | {setMap: (map: unknown) => void}>>([]);
  const fittedPointsKeyRef = useRef<string | null>(null);
  const selectionMarkerRef = useRef<MapMarker | null>(null);
  const selectionDragRef = useRef<{remove: () => void} | null>(null);
  const onSelectRef = useRef(onSelect);
  const selectionActiveRef = useRef(Boolean(selection?.active));
  const [error, setError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);

  const pointKey = points.map(p => `${p.label}:${p.latitude ?? ""}:${p.longitude ?? ""}`).join("|");
  const latestKey = latest ? `${latest.lat}:${latest.lng}` : "";
  const selectionPointKey = selection?.point ? `${selection.point.lat}:${selection.point.lng}` : "";

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);
  useEffect(() => { selectionActiveRef.current = Boolean(selection?.active); }, [selection?.active]);

  // Create the Google map once. Polling the tracking endpoint must not rebuild it.
  useEffect(() => {
    if (!apiKey || !ref.current) return;
    let disposed = false;
    let clickListener: {remove: () => void} | undefined;
    loadMaps(apiKey).then(g => {
      if (disposed || !ref.current) return;
      googleRef.current = g;
      const map = new g.maps.Map(ref.current, {zoom:6, center:{lat:-34.6,lng:-58.4}, mapId:"DEMO_MAP_ID", streetViewControl:false});
      mapRef.current = map;
      clickListener = map.addListener("click", event => {
        if (selectionActiveRef.current && event.latLng) onSelectRef.current?.({lat:event.latLng.lat(),lng:event.latLng.lng()});
      });
      setMapReady(true);
    }).catch((reason: Error) => { if (!disposed) setError(reason.message); });
    return () => {
      disposed = true;
      clickListener?.remove();
      selectionDragRef.current?.remove();
      selectionMarkerRef.current && (selectionMarkerRef.current.map = null);
      overlaysRef.current.forEach(overlay => "setMap" in overlay ? overlay.setMap(null) : overlay.map = null);
      overlaysRef.current = [];
      fittedPointsKeyRef.current = null;
      mapRef.current = null;
      googleRef.current = null;
      setMapReady(false);
    };
  }, [apiKey]);

  // Refresh route overlays only when their actual coordinates or route change.
  useEffect(() => {
    const map = mapRef.current;
    const g = googleRef.current;
    if (!map || !g || !mapReady) return;
    overlaysRef.current.forEach(overlay => "setMap" in overlay ? overlay.setMap(null) : overlay.map = null);
    overlaysRef.current = [];
    const bounds = new g.maps.LatLngBounds();
    const validPoints = points.filter((p): p is RoutePoint & {latitude:number;longitude:number} => p.latitude !== null && p.longitude !== null);
    validPoints.forEach((p,i) => {
      const position = {lat:p.latitude,lng:p.longitude}; bounds.extend(position);
      const content = document.createElement("span"); content.className = "map-point-label"; content.textContent = i === 0 ? "A" : i === validPoints.length - 1 ? "B" : String(i);
      overlaysRef.current.push(new g.maps.marker.AdvancedMarkerElement({map, position, title:p.label, content}));
    });
    if (latest) {
      bounds.extend(latest);
      const content = document.createElement("span"); content.className = "map-truck-label"; content.textContent = "🚚";
      overlaysRef.current.push(new g.maps.marker.AdvancedMarkerElement({map, position:latest, title:"Última ubicación informada", content}));
    }
    if (polyline) overlaysRef.current.push(new g.maps.Polyline({map, path:decodePolyline(polyline), strokeColor:"#166534", strokeWeight:4}));
    // Fit the trip only when route endpoints change. New GPS reports just move their marker.
    if (validPoints.length && fittedPointsKeyRef.current !== pointKey) {
      map.fitBounds(bounds, 48);
      fittedPointsKeyRef.current = pointKey;
    }
  }, [mapReady, pointKey, latestKey, polyline]);

  // Focus the selected endpoint and show a draggable preview pin without saving it.
  useEffect(() => {
    const map = mapRef.current;
    const g = googleRef.current;
    if (!map || !g || !mapReady) return;
    selectionDragRef.current?.remove();
    selectionDragRef.current = null;
    if (selectionMarkerRef.current) selectionMarkerRef.current.map = null;
    selectionMarkerRef.current = null;
    map.setOptions({draggableCursor:selection?.active ? "crosshair" : null});
    if (!selection?.active) return;
    if (selection.point) {
      map.panTo(selection.point);
      map.setZoom(15);
      const content = document.createElement("span"); content.className = "map-selection-label"; content.textContent = "📍";
      const marker = new g.maps.marker.AdvancedMarkerElement({map, position:selection.point, title:"Arrastrá para ajustar el punto", content, gmpDraggable:true});
      selectionMarkerRef.current = marker;
      selectionDragRef.current = marker.addListener("dragend", event => {
        const position = plainPoint(event.latLng ?? marker.position);
        if (position) onSelectRef.current?.(position);
      });
    } else {
      map.setZoom(13);
    }
  }, [mapReady, selection?.active, selectionPointKey]);

  if (!apiKey) return <p className="state-box">El mapa está pendiente de configurar Google Maps. Las ubicaciones y controles siguen disponibles.</p>;
  return <><div className={`google-route-map-shell${selection?.active ? " is-selecting" : ""}`}><div ref={ref} className="google-route-map" aria-label="Recorrido estimado y última posición informada del camión" />{selection?.active ? <div className="map-selection-hint">📍 Ajustá el punto arrastrándolo o hacé clic en el mapa.</div> : null}</div>{error ? <p role="alert">{error}</p> : null}</>;
}
