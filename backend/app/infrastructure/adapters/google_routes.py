"""Google is a route estimator, never a truck road-eligibility validator."""
from urllib.parse import urlencode
import httpx


class RouteUnavailable(ValueError):
    pass


def maps_url(origin, destination, stops=()):
    def label(p):
        return f"{p['latitude']},{p['longitude']}" if p.get("latitude") is not None else p["label"]
    params = {"api": "1", "origin": label(origin), "destination": label(destination), "travelmode": "driving"}
    if stops:
        params["waypoints"] = "|".join(label(p) for p in stops)
    return "https://www.google.com/maps/dir/?" + urlencode(params)


class GoogleRoutes:
    def __init__(self, api_key=None, client=None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=12)

    def calculate(self, points):
        if not self.api_key:
            raise RouteUnavailable("Google Routes todavía no está configurado")
        if len(points) < 2 or len(points) > 12:
            raise RouteUnavailable("El recorrido admite hasta diez paradas intermedias")
        def waypoint(p):
            if p.get("latitude") is None:
                return {"address": p["label"] + ", Argentina"}
            return {"location": {"latLng": {"latitude": p["latitude"], "longitude": p["longitude"]}}}
        try:
            response = self.client.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"},
                json={"origin": waypoint(points[0]), "destination": waypoint(points[-1]), "intermediates": [waypoint(p) for p in points[1:-1]], "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE", "languageCode": "es-AR", "units": "METRIC"},
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
            duration = float(route["duration"].removesuffix("s"))
            distance = int(route["distanceMeters"])
            if duration <= 0 or distance < 0:
                raise ValueError("invalid route")
            return {"distance_meters": distance, "duration_seconds": duration, "polyline": route.get("polyline", {}).get("encodedPolyline", "")}
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            # Do not include request headers or provider body in errors/logs.
            raise RouteUnavailable("No pudimos calcular el recorrido en Google") from None
