"""Declared route dispatch and evidence-based, sparse trip tracking."""
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import csv
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.application.contact_mapping import normalize_phone_number
from app.domain.cargo import convert_mass_quantity, normalize_cargo_type, normalize_quantity_unit
from app.domain.equipment import normalize_equipment_or_declared
from app.domain.location_catalog import CATALOG_PATH, fold_location, resolve_catalog_locality
from app.domain.routing import RoutingEntry, aware, coordinates
from app.domain.events import current_test_run_id
from app.infrastructure.adapters.google_routes import GoogleRoutes, RouteUnavailable, maps_url
from app.infrastructure.adapters.whatsapp import OutboundAction, OutboundMessage

AR = ZoneInfo("America/Argentina/Buenos_Aires")
OPEN_LOADS = {"PUBLISHED", "MATCHING"}


def key(*values):
    return "rt_" + sha256("|".join(str(v) for v in values).encode()).hexdigest()[:40]


@lru_cache(maxsize=1)
def georef_rows():
    with CATALOG_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class RoutingService:
    def __init__(self, *, store, shipments, carriers, availabilities, offers, trips, drivers,
                 locations, conversations, events, notifications=None, provider=None,
                 maps=None, geography=None, cargo_catalog=None, category_catalog=None, daily_route_limit=100, clock=None):
        self.store, self.shipments, self.carriers = store, shipments, carriers
        self.availabilities, self.offers, self.trips, self.drivers = availabilities, offers, trips, drivers
        self.locations, self.conversations, self.events = locations, conversations, events
        self.notifications, self.provider = notifications, provider
        self.maps, self.geography = maps or GoogleRoutes(), geography
        self.cargo_catalog, self.category_catalog = cargo_catalog, category_catalog
        self.daily_route_limit = daily_route_limit
        self.last_dispatch_results = []
        self.clock = clock or (lambda: datetime.now(UTC))

    def event(self, kind, entry, summary, **payload):
        self.events.record(event_type=kind, actor_type="System", entity_type="RouteOperation", entity_id=entry.id,
                           test_run_id=entry.test_run_id, summary=summary, payload=payload, source="route_operations")

    def node(self, value):
        """Resolve by canonical ID, or unambiguous locality + province. Never match by city alone."""
        if not value:
            raise ValueError("Falta la localidad")
        parts = [p.strip() for p in str(value).split(",")]
        if self.geography is not None:
            direct = next((e for e in self.geography if e.kind == "LOCALITY" and value in {e.id, e.georef_id}), None)
            resolution = resolve_catalog_locality(direct.name if direct else parts[0], self.geography)
            candidates = list(resolution.candidates)
            if direct:
                candidates = [c for c in candidates if c.georef_id == (direct.georef_id or direct.id)]
            if len(parts) > 1:
                candidates = [c for c in candidates if fold_location(c.province) == fold_location(parts[-1])]
            if len(candidates) == 1:
                c = candidates[0]
                result = {"id": c.georef_id, "label": f"{c.name}, {c.province}"}
                row = next((r for r in georef_rows() if r["id"] == c.georef_id), None)
                return {**result, **self._centroid(row)}
            if len(candidates) > 1:
                raise ValueError("Hay localidades homónimas. Indicá localidad y provincia")
            raise ValueError("No encontré la localidad en el catálogo activo")
        rows = [r for r in georef_rows() if r.get("categoria") != "Entidad" and (r["id"] == value or fold_location(r["nombre"]) == fold_location(parts[0]))]
        if len(parts) > 1:
            rows = [r for r in rows if fold_location(r["provincia_nombre"]) == fold_location(parts[-1])]
        if len(rows) != 1:
            raise ValueError("Indicá una localidad del catálogo y su provincia; no puedo resolverla de forma única")
        r = rows[0]
        return {"id": r["id"], "label": f"{r['nombre']}, {r['provincia_nombre']}", **self._centroid(r)}

    @staticmethod
    def _centroid(row):
        if row and row.get("centroide_lat") and row.get("centroide_lon"):
            return {"latitude": float(row["centroide_lat"]), "longitude": float(row["centroide_lon"]), "precision": "LOCALITY_CENTROID", "source": "GEOREF"}
        return {"latitude": None, "longitude": None, "precision": "UNRESOLVED"}

    def point(self, location_id):
        loc = self.locations.get(location_id) if location_id else None
        if loc is None:
            raise ValueError("La carga necesita origen y destino")
        result = self.node(loc.georef_id or loc.original_text)
        if loc.latitude is not None and loc.longitude is not None:
            result.update(latitude=loc.latitude, longitude=loc.longitude, precision=loc.coordinate_precision, source=loc.coordinate_source)
        return result

    def cargo_type(self, value):
        return normalize_cargo_type(value, types=self.cargo_catalog, categories=self.category_catalog)

    def dispatch_eligible(self, carrier, scope):
        if not carrier.is_validated:
            return False
        if carrier.validation_status == "APPROVED":
            return True
        # Synthetic QA carriers may participate only inside their active
        # scenario and only when their contact is the scenario participant.
        if not scope or carrier.validation_status != "QA_ONLY":
            return False
        phone = self.phone(carrier.normalized_phone_number or carrier.contact_phone)
        return bool(phone) and any(
            conversation.active_test_run_id == scope
            and conversation.status == "OPEN"
            and self.phone(conversation.participant_phone or conversation.normalized_phone_number) == phone
            for conversation in self.conversations.list()
        )

    def save_preference(self, carrier_id, data, scope, preference_id=None, actor="operator"):
        if not self.carriers.get(carrier_id):
            raise ValueError("Transportista no encontrado")
        points = [self.node(v) for v in [data['origin'], *data.get('stops', []), data['destination']]]
        if len(points) > 12 or len({p['id'] for p in points}) != len(points):
            raise ValueError("El recorrido debe tener entre dos y doce localidades distintas")
        from app.domain.cargo import normalize_cargo_category
        categories = [normalize_cargo_category(c, self.category_catalog) for c in data.get("cargo_categories", [])]
        types = [self.cargo_type(v) for v in data.get("cargo_types", [])]
        if not categories and not types:
            raise ValueError("Indicá al menos una categoría o tipo de carga")
        if any(c not in {"LIVESTOCK", "GRAIN"} for c in categories) or any(not c for c in types):
            raise ValueError("Categoría o tipo de carga desconocido")
        old = self.store.get(preference_id) if preference_id else None
        if preference_id and (not old or old.kind != "preference" or old.entity_id != carrier_id or old.test_run_id != scope):
            raise ValueError("Recorrido habitual no encontrado en este contexto")
        entry = old or RoutingEntry(kind="preference", entity_id=carrier_id, test_run_id=scope)
        entry.status = "ACTIVE" if data.get("active", True) else "PAUSED"
        entry.data = {"points": points, "cargo_categories": categories, "cargo_types": types,
                      "equipment_types": [normalize_equipment_or_declared(v) for v in data.get("equipment_types", [])],
                      "opt_in": data.get("opt_in", False), "updated_by": actor}
        self.store.put(entry)
        self.event("CARRIER_ROUTE_PREFERENCE_UPDATED", entry, "Recorrido habitual actualizado")
        return entry

    @staticmethod
    def segment(points, origin, destination):
        ids = [p['id'] for p in points]
        return origin in ids and destination in ids and ids.index(origin) < ids.index(destination)

    def compatible(self, availability, shipment, origin, destination):
        if availability.test_run_id != shipment.test_run_id or availability.status != "ACTIVE":
            return False
        now = aware(self.clock())
        if not availability.window_start or not availability.window_end or aware(availability.window_end) < now:
            return False
        if not shipment.date_window_start or not aware(availability.window_start) <= aware(shipment.date_window_start) <= aware(availability.window_end):
            return False
        if shipment.date_window_end and aware(shipment.date_window_end) > aware(availability.window_end):
            return False
        try:
            points = [self.node(v) for v in availability.route]
            if not self.segment(points, origin, destination):
                return False
            if not self.cargo_type(shipment.cargo_type) or self.cargo_type(shipment.cargo_type) not in {self.cargo_type(c) for c in availability.cargo_types}:
                return False
            required_equipment = normalize_equipment_or_declared(shipment.required_equipment_type)
            if required_equipment and required_equipment not in {normalize_equipment_or_declared(e) for e in availability.equipment_types}:
                return False
            if not availability.equipment_types or shipment.quantity_estimate is None or availability.capacity is None:
                return False
            source, target = normalize_quantity_unit(shipment.quantity_unit), normalize_quantity_unit(availability.capacity_unit)
            amount = shipment.quantity_estimate if source == target and source else convert_mass_quantity(shipment.quantity_estimate, source, target)
            return amount <= availability.capacity
        except (ValueError, TypeError, ArithmeticError):
            return False

    def publish(self, shipment, *, fallback=False):
        self.last_dispatch_results = []
        scope = shipment.test_run_id
        with self.store.lock("shipment:" + shipment.id):
            shipment = self.shipments.get(shipment.id)
            if shipment.status not in OPEN_LOADS or self.closed(scope):
                return []
            if fallback and any(o.shipment_request_id == shipment.id and o.test_run_id == scope and o.response_type == "INTERESTED" and o.status not in {"REJECTED", "CANCELLED", "EXPIRED"} for o in self.offers.list()):
                return []
            reason = "date_unresolved"
            try:
                if not self.cargo_type(shipment.cargo_type):
                    reason = 'cargo_unresolved'
                    raise ValueError('Tipo de carga fuera del catálogo activo')
                if shipment.date_window_start is None:
                    raise ValueError('Falta confirmar la fecha de la carga')
                end = aware(shipment.date_window_end) if shipment.date_window_end else aware(shipment.date_window_start).astimezone(AR).replace(hour=23, minute=59, second=59)
                if end < aware(self.clock()):
                    reason = 'shipment_expired'
                    raise ValueError('La ventana de la carga venció')
                reason = 'geography_unresolved'
                origin, destination = self.point(shipment.origin_location_id)['id'], self.point(shipment.destination_location_id)['id']
            except ValueError:
                item = RoutingEntry(kind="dispatch", entity_id=shipment.id, test_run_id=scope, id=key("dispatch-invalid", shipment.id), status="REVIEW", data={"reason": reason})
                self.store.put(item); self.event("ROUTE_DISPATCH_REVIEW", item, "Falta resolver fecha o geografía de la carga", reason=reason)
                shipment.requires_human_review = True; self.shipments.save(shipment)
                return []
            candidates = {}
            if not fallback:
                for a in self.availabilities.list():
                    if self.compatible(a, shipment, origin, destination):
                        candidates.setdefault(a.carrier_id, a.id)
            candidates = {cid: aid for cid, aid in candidates.items() if (c := self.carriers.get(cid)) and self.dispatch_eligible(c, scope) and self.phone(c.normalized_phone_number or c.contact_phone)}
            stage = "AVAILABILITY" if candidates and not fallback else "PREFERENCE"
            if stage == "PREFERENCE":
                for pref in self.store.list("preference", scope):
                    if pref.status == "ACTIVE" and pref.data.get("opt_in") and self.segment(pref.data['points'], origin, destination) and (not shipment.required_equipment_type or normalize_equipment_or_declared(shipment.required_equipment_type) in pref.data['equipment_types']):
                        if shipment.cargo_category in pref.data['cargo_categories'] or self.cargo_type(shipment.cargo_type) in pref.data['cargo_types']:
                            candidates.setdefault(pref.entity_id, None)
            selected = []
            for carrier in self.carriers.list():
                decision_id = key("dispatch", shipment.id, carrier.id)
                existing = self.store.get(decision_id)
                if existing and existing.status in {"QUEUED", "ACCEPTED", "RECONCILE_REQUIRED", "FAILED"}:
                    continue
                reason = "compatible_declared_segment" if carrier.id in candidates else "no_compatible_declared_route"
                eligible = carrier.id in candidates and self.dispatch_eligible(carrier, scope)
                if not self.dispatch_eligible(carrier, scope):
                    reason = "not_approved"
                if not (carrier.contact_phone or carrier.normalized_phone_number):
                    eligible, reason = False, "missing_contact"
                if scope:
                    phones = {self.phone(s.participant_phone) for s in self.conversations.list() if s.active_test_run_id == scope}
                    if self.phone(carrier.normalized_phone_number or carrier.contact_phone) not in phones:
                        eligible, reason = False, "outside_qa_participant"
                entry = RoutingEntry(kind="dispatch", entity_id=shipment.id, test_run_id=scope, id=decision_id,
                                     status="SELECTED" if eligible else "EXCLUDED", data={"carrier_id": carrier.id, "stage": stage, "reason": reason, "availability_id": candidates.get(carrier.id)})
                self.store.put(entry)
                if not eligible:
                    continue
                self.events.record(event_type="CARRIER_NOTIFIED", actor_type="System", entity_type="ShipmentRequest", entity_id=shipment.id,
                                   test_run_id=scope, summary="Transportista seleccionado por recorrido declarado", payload={"carrier_id": carrier.id, "stage": stage}, related_entity_ids={"carrierId": carrier.id, "loadId": shipment.id}, idempotency_key=key("selected", shipment.id, carrier.id))
                selected.append(carrier.id)
                if self.notifications:
                    token = current_test_run_id.set(scope)
                    try:
                        result = self.notifications.send_new_load_alert(shipment=shipment, carrier_id=carrier.id, operator_user_id=None, route_context={"stage": stage, "availability_id": candidates.get(carrier.id), **({"qa_role": "Carrier"} if scope else {})})
                    finally:
                        current_test_run_id.reset(token)
                    self.last_dispatch_results.append(result)
                    entry.status = "QUEUED" if result.status == "queued" else "ACCEPTED" if result.status in {"sent", "skipped_duplicate"} else "FAILED"
                    self.store.put(entry)
                self.event("ROUTE_DISPATCH_SELECTED", entry, "Oportunidad dirigida por recorrido", stage=stage)
            if stage == "AVAILABILITY":
                self.schedule(shipment.id, scope, "EXPAND", aware(self.clock()) + timedelta(minutes=30))
            if not selected and not any(e.status in {'QUEUED','ACCEPTED'} for e in self.store.list('dispatch', scope, entity_id=shipment.id)):
                shipment.requires_human_review = True; self.shipments.save(shipment)
                if self.notifications and shipment.producer_phone_number:
                    self.notifications.send_producer_message(phone_number=shipment.producer_phone_number,
                        body='📦 Tu carga está publicada. Todavía no encontramos transportistas con recorridos declarados compatibles; soporte puede revisarla.',
                        entity_type='ShipmentRequest', entity_id=shipment.id, operator_user_id='route_worker', idempotency_key=key('no-recipients',shipment.id), notification_type='ROUTE_DISPATCH_EMPTY')
            if not selected:
                self.event("ROUTE_DISPATCH_NO_RECIPIENTS", RoutingEntry(kind="dispatch", entity_id=shipment.id, test_run_id=scope, id=key("empty", shipment.id)), "No hay destinatarios compatibles nuevos")
            return selected

    def commit_availability(self, shipment, carrier_id):
        with self.store.lock("shipment:" + shipment.id):
            decision = self.store.get(key("dispatch", shipment.id, carrier_id))
            aid = decision.data.get("availability_id") if decision else None
            if aid:
                with self.store.lock("availability:" + aid):
                    availability = self.availabilities.get(aid)
                    if availability is None or availability.test_run_id != shipment.test_run_id or availability.carrier_id != carrier_id:
                        raise ValueError("Disponibilidad fuera del contexto de la carga")
                    if availability.committed_shipment_id == shipment.id:
                        return
                    origin, destination = self.point(shipment.origin_location_id)['id'], self.point(shipment.destination_location_id)['id']
                    if not self.compatible(availability, shipment, origin, destination):
                        raise ValueError("La disponibilidad ya no está libre o dejó de ser compatible")
                    availability.status, availability.committed_shipment_id = "COMMITTED", shipment.id
                    self.availabilities.save(availability)
                    self.event("ROUTE_AVAILABILITY_COMMITTED", decision, "Disponibilidad comprometida a una carga")
            self.cancel_jobs(shipment.id, shipment.test_run_id, "EXPAND")

    def schedule(self, entity_id, scope, action, due, suffix="", **data):
        job_id = key("job", entity_id, scope, action, suffix)
        if not self.store.get(job_id):
            self.store.put(RoutingEntry(kind="job", entity_id=entity_id, test_run_id=scope, id=job_id, due_at=due, status="PENDING", data={"action": action, **data}))

    def cancel_jobs(self, entity_id, scope, action=None):
        for job in self.store.list("job", scope, entity_id=entity_id):
            if job.status == "PENDING" and job.data.get("action") != "EXPIRE_ROUTE" and (action is None or job.data['action'] == action):
                job.status = "CANCELLED"; self.store.put(job)

    def closed(self, scope):
        return bool(scope and self.store.get(key("closed", scope)))

    def close_run(self, scope):
        self.store.put(RoutingEntry(kind="closed_run", entity_id=scope, test_run_id=scope, id=key("closed", scope)))
        for kind in ("job", "checkpoint"):
            for item in self.store.list(kind, scope):
                if item.status in {"PENDING", "REQUESTED", "SELECTED"} and item.data.get("action") != "EXPIRE_ROUTE":
                    item.status = "CANCELLED"; self.store.put(item)

    def confirm_driver(self, trip_id, scope, actor):
        trip = self.trip(trip_id, scope)
        driver = self.drivers.get(trip.driver_id) if trip.driver_id else None
        if not driver or driver.carrier_id != trip.carrier_id or driver.validation_status != "APPROVED" or driver.status != "ACTIVE" or not self.phone(driver.phone):
            raise ValueError("Asigná un chofer aprobado con WhatsApp válido antes de confirmar seguimiento")
        entry = self.store.get(key("tracking", trip.id)) or RoutingEntry(kind="tracking", entity_id=trip.id, test_run_id=scope, id=key("tracking", trip.id))
        entry.data.update(driver_id=driver.id, driver_phone=self.phone(driver.phone), confirmed_by=actor, confirmed_at=aware(self.clock()).isoformat())
        self.store.put(entry)
        self.event("TRIP_TRACKING_DRIVER_CONFIRMED", entry, "Contacto del chofer confirmado para seguimiento")
        return entry

    def trip(self, trip_id, scope):
        trip = self.trips.get(trip_id)
        if not trip or trip.test_run_id != scope:
            raise ValueError("Viaje no encontrado en este contexto")
        return trip

    def transit(self, trip):
        tracking = self.store.get(key("tracking", trip.id))
        if not tracking or tracking.data.get("driver_id") != trip.driver_id:
            self.event("TRIP_TRACKING_REQUIRES_CONTACT", RoutingEntry(kind="tracking", entity_id=trip.id, test_run_id=trip.test_run_id), "Confirmar contacto del chofer para seguimiento")
            return
        tracking.data.setdefault('transit_at', aware(self.clock()).isoformat())
        self.store.put(tracking)
        self.schedule(trip.id, trip.test_run_id, "BEGIN_TRACKING", aware(self.clock()))

    def _route_points(self, trip):
        shipment = self.shipments.get(trip.shipment_request_id)
        origin, destination = self.point(shipment.origin_location_id), self.point(shipment.destination_location_id)
        decision = self.store.get(key("dispatch", shipment.id, trip.carrier_id))
        availability = self.availabilities.get(decision.data.get("availability_id")) if decision and decision.data.get("availability_id") else None
        stops = []
        if availability:
            points = [self.node(v) for v in availability.route]
            ids = [p['id'] for p in points]
            if self.segment(points, origin['id'], destination['id']):
                stops = points[ids.index(origin['id']) + 1:ids.index(destination['id'])]
        return [origin, *stops, destination]

    def calculate(self, tracking, points, remaining=False):
        now = aware(self.clock())
        usage_id = key("usage", now.date())
        with self.store.lock(usage_id):
            usage = self.store.get(usage_id) or RoutingEntry(kind="usage", entity_id=str(now.date()), id=usage_id, data={"count": 0})
            if usage.data['count'] >= self.daily_route_limit:
                raise RouteUnavailable("Se alcanzó la cuota diaria de cálculos")
            # Count failed calls too. Provider key is never stored in operation data.
            usage.data['count'] += 1; self.store.put(usage)
        route = self.maps.calculate(points)
        tracking.data["remaining_route" if remaining else "route"] = route
        tracking.data.update(route_calculated_at=now.isoformat(), route_expires_at=(now + timedelta(hours=24)).isoformat(), route_status="AVAILABLE")
        self.store.put(tracking)
        self.schedule(tracking.entity_id, tracking.test_run_id, "EXPIRE_ROUTE", now + timedelta(hours=24), suffix=now.isoformat(), version=now.isoformat())
        return route

    def begin_tracking(self, trip):
        tracking = self.store.get(key("tracking", trip.id))
        if not tracking or tracking.data.get("began_at"):
            return
        driver = self.drivers.get(trip.driver_id)
        if not driver or tracking.data.get("driver_id") != driver.id or tracking.data.get("driver_phone") != self.phone(driver.phone):
            self.event("TRIP_TRACKING_REQUIRES_CONTACT", tracking, "Cambió el chofer; confirmar nuevamente el contacto")
            return
        tracking.data['began_at'] = tracking.data.get('transit_at') or aware(self.clock()).isoformat()
        try:
            points = self._route_points(trip)
            tracking.data['points'] = points
            route = self.calculate(tracking, points)
            duration = route['duration_seconds']
            self.schedule(trip.id, trip.test_run_id, "CHECKPOINT", datetime.fromisoformat(tracking.data['began_at']) + timedelta(seconds=duration / 2), suffix="MIDDLE", stage="MIDDLE")
            self.schedule(trip.id, trip.test_run_id, "CHECKPOINT", datetime.fromisoformat(tracking.data['began_at']) + timedelta(seconds=duration), suffix="ARRIVAL", stage="ARRIVAL")
            body = f"🚚 Recorrido orientativo: {points[0]['label']} → {points[-1]['label']}\n📏 {route['distance_meters']/1000:.1f} km · ⏱️ {int(duration//60)} min de conducción, sin descansos.\n📍 Los centros de localidad son aproximados; confirmá los accesos rurales.\n{maps_url(points[0], points[-1], points[1:-1])}\nPara informar llegada: /viaje {trip.id} llegue"
            self.send_driver(tracking, body, "route", message_type="text")
        except (ValueError, RouteUnavailable) as exc:
            tracking.data.update(route_status="PENDING", route_error=str(exc))
            self.event("TRIP_ROUTE_PENDING", tracking, "Ruta pendiente de cálculo; seguimiento manual disponible")
        self.store.put(tracking)
        self.request_checkpoint(trip.id, trip.test_run_id, "DEPARTURE")
        self.producer_update(trip, "🚚 El chofer informó la salida. El viaje está en tránsito.", "departure")

    def request_checkpoint(self, trip_id, scope, stage="MANUAL", request_key=None):
        trip = self.trip(trip_id, scope)
        if trip.status not in {"IN_TRANSIT", "DELIVERED"} or self.closed(scope):
            raise ValueError("El viaje no admite controles de ubicación")
        tracking = self.store.get(key("tracking", trip.id))
        if not tracking or not tracking.data.get("driver_phone"):
            raise ValueError("Falta confirmar el WhatsApp del chofer")
        driver = self.drivers.get(trip.driver_id)
        if not driver or driver.status != "ACTIVE" or driver.validation_status != "APPROVED" or driver.id != tracking.data.get("driver_id") or self.phone(driver.phone) != tracking.data.get("driver_phone"):
            raise ValueError("Cambió el chofer o su teléfono; confirmá nuevamente el contacto")
        cp_id = key("checkpoint", trip.id, stage, request_key or "")
        existing = self.store.get(cp_id)
        if existing:
            return existing
        now = aware(self.clock())
        cp = RoutingEntry(kind="checkpoint", entity_id=trip.id, test_run_id=scope, id=cp_id, status="REQUESTED", data={"stage": stage, "driver_id": trip.driver_id, "phone": tracking.data['driver_phone'], "requested_at": now.isoformat()})
        self.store.put(cp)
        labels = {"DEPARTURE": "salida", "MIDDLE": "mitad del viaje", "ARRIVAL": "llegada", "MANUAL": "control solicitado por soporte"}
        result = self.send_driver(tracking, f"📍 Compartí tu ubicación actual para registrar la {labels[stage]}.\nSi necesitás ayuda: /viaje {trip.id} ayuda", cp.id, message_type="location_request", metadata={"checkpoint_id": cp.id})
        cp.data.update(provider_message_id=result.provider_message_id if result else None)
        self.store.put(cp)
        self.schedule(trip.id, scope, "REMIND", now + timedelta(minutes=15), suffix=cp.id, checkpoint_id=cp.id)
        self.schedule(trip.id, scope, "OVERDUE", now + timedelta(minutes=30), suffix=cp.id, checkpoint_id=cp.id)
        self.event("TRIP_LOCATION_REQUESTED", cp, "Ubicación solicitada al chofer", stage=stage)
        return cp

    def send_driver(self, tracking, body, suffix, message_type="text", metadata=None):
        if not self.provider:
            return None
        from app.application.interactive import prepare_outbound_message
        actions = ()
        if suffix == 'route':
            actions = (OutboundAction(id=f"trip-arrival:{tracking.entity_id}", label="📍 Informar llegada", value=f"/viaje {tracking.entity_id} llegue"),
                       OutboundAction(id=f"trip-help:{tracking.entity_id}", label="💬 Necesito ayuda", value=f"/viaje {tracking.entity_id} ayuda"))
        outbound = OutboundMessage(conversation_id=tracking.data['driver_phone'], body=body, message_type=message_type,
            allowlist_phone_number=tracking.data['driver_phone'], correlation_id=key(tracking.id, suffix),
            metadata={"entity_type": "Trip", "entity_id": tracking.entity_id, "qa_role": "Carrier", "qa_test_run_id": tracking.test_run_id,
                      "notification_type": "TRIP_TRACKING", "outbox_idempotency_key": key(tracking.id, suffix), **(metadata or {})}, actions=actions)
        prepared, _ = prepare_outbound_message(outbound, self.provider.capabilities)
        return self.provider.send_message(prepared)

    def producer_update(self, trip, text, suffix):
        shipment = self.shipments.get(trip.shipment_request_id)
        if self.notifications and shipment.producer_phone_number:
            token = current_test_run_id.set(trip.test_run_id)
            try:
                self.notifications.send_producer_message(phone_number=shipment.producer_phone_number, body=text,
                    entity_type="Trip", entity_id=trip.id, operator_user_id="route_worker", idempotency_key=key("producer-track", trip.id, suffix), notification_type="TRIP_TRACKING")
            finally:
                current_test_run_id.reset(token)

    @staticmethod
    def phone(value):
        try:
            return normalize_phone_number(value) if value else None
        except ValueError:
            return None

    def receive_location(self, inbound, scope, selected_checkpoint=None):
        lat, lng = coordinates(float(inbound.location['latitude']), float(inbound.location['longitude']))
        report_id = key("report", inbound.provider, inbound.provider_message_id or inbound.idempotency_key)
        old = self.store.get(report_id)
        if old and old.status != "AWAITING_SELECTION":
            return "✅ Esa ubicación ya quedó registrada.", ()
        phone = self.phone(inbound.phone_number)
        quoted = self.store.checkpoint_for_reply(inbound.reply_to_message_id) if inbound.reply_to_message_id and hasattr(self.store, 'checkpoint_for_reply') else None
        candidates = [c for c in self.store.list("checkpoint", scope) if c.status in {"REQUESTED", "OVERDUE"} and c.data.get("phone") == phone]
        if quoted:
            cp = self.store.get(quoted)
            candidates = [cp] if cp and cp.data.get("phone") == phone else []
        else:
            candidates = [c for c in candidates if c.id == selected_checkpoint] if selected_checkpoint else candidates
        report = old or RoutingEntry(kind="report", entity_id="unassigned", id=report_id, test_run_id=scope, status="AWAITING_SELECTION", data={"latitude": lat, "longitude": lng, "phone": phone, "source_message_id": inbound.provider_message_id, "occurred_at": aware(inbound.occurred_at or self.clock()).isoformat(), "received_at": aware(self.clock()).isoformat()})
        if quoted and len(candidates) == 1:
            report.test_run_id = candidates[0].test_run_id
        self.store.put(report)
        if len(candidates) != 1 or (not quoted and not selected_checkpoint):
            actions = tuple(OutboundAction(id=f"link:{report.id}:{c.id}", label=f"{ {'DEPARTURE':'Salida','MIDDLE':'Mitad','ARRIVAL':'Llegada','MANUAL':'Control','ACCESS':'Acceso'}.get(c.data['stage'],'Control')} {c.entity_id[-6:]}", value=f"/ubicacion {report.id} {c.id}") for c in candidates[:10])
            return "📍 Recibí el punto. Elegí a qué control corresponde antes de guardarlo." if actions else "📍 No hay un control asociado a este mensaje. Solicitá un control de ubicación desde tu viaje.", actions
        return self.link_report(report, candidates[0], phone), ()

    def link_report(self, report, cp, phone):
        with self.store.lock("checkpoint:" + cp.id):
            cp = self.store.get(cp.id)
            if report.data['phone'] != phone or cp.data['phone'] != phone:
                raise ValueError("No podés asociar esta ubicación")
            if report.status != "AWAITING_SELECTION":
                return "✅ Esa ubicación ya quedó registrada."
            if report.test_run_id != cp.test_run_id:
                raise ValueError("La ubicación pertenece a otro escenario")
            report.entity_id = cp.entity_id
            report.data['checkpoint_id'] = cp.id
            late = self.closed(cp.test_run_id) or cp.status == "CANCELLED"
            if not late:
                if cp.data.get('location_id'):
                    shipment = self.shipments.get(cp.entity_id)
                    if not shipment or shipment.test_run_id != cp.test_run_id or self.phone(shipment.producer_phone_number) != phone:
                        raise ValueError('El productor ya no corresponde al acceso solicitado')
                else:
                    bound_trip = self.trip(cp.entity_id, cp.test_run_id)
                    bound_driver = self.drivers.get(bound_trip.driver_id)
                    if not bound_driver or bound_driver.status != 'ACTIVE' or bound_driver.validation_status != 'APPROVED' or bound_driver.id != cp.data.get('driver_id') or self.phone(bound_driver.phone) != phone:
                        raise ValueError('El chofer del viaje cambió; solicitá un control nuevo')
                    late = bound_trip.status in {'CANCELLED', 'COMPLETED'}
            report.status = "LATE" if late else "RECEIVED"
            self.store.put(report)
            if late:
                self.event("TRIP_LOCATION_LATE", report, "Ubicación tardía conservada sin modificar otro escenario")
                return "📍 Conservé la ubicación en el escenario anterior; no modifica el viaje actual."
            if cp.status == "RECEIVED":
                report.status = "DUPLICATE_CONTROL"; self.store.put(report)
                return "✅ Este control ya tenía una ubicación registrada."
            if aware(datetime.fromisoformat(report.data['occurred_at'])) < aware(datetime.fromisoformat(cp.data['requested_at'])):
                report.status = "LATE"; self.store.put(report)
                return "📍 El punto es anterior a este control y quedó conservado como tardío."
            if cp.data.get('location_id'):
                shipment = self.shipments.get(cp.entity_id)
                if not shipment or self.phone(shipment.producer_phone_number) != phone:
                    raise ValueError("La carga ya no pertenece a este contacto")
                loc = self.locations.get(cp.data['location_id'])
                if not loc:
                    raise ValueError("La carga no tiene esa localidad")
                loc.latitude, loc.longitude = report.data['latitude'], report.data['longitude']
                loc.coordinate_source, loc.coordinate_precision = 'WHATSAPP_DECLARED', 'CONFIRMED_ACCESS'
                self.locations.save(loc)
                cp.status = 'RECEIVED'; self.store.put(cp)
                self.event('SHIPMENT_LOCATION_CONFIRMED', report, 'Productor informó punto exacto del acceso')
                return '✅ Punto de acceso guardado para la carga.'
            trip = self.trip(cp.entity_id, cp.test_run_id)
            driver = self.drivers.get(trip.driver_id)
            if not driver or driver.id != cp.data['driver_id'] or self.phone(driver.phone) != phone:
                raise ValueError("El chofer del viaje cambió; solicitá un control nuevo")
            cp.status = "RECEIVED"; cp.data['report_id'] = report.id; self.store.put(cp)
            tracking = self.store.get(key("tracking", trip.id))
            previous = tracking.data.get("latest_report_at")
            stamp = report.data['occurred_at']
            if previous is None or datetime.fromisoformat(stamp) >= datetime.fromisoformat(previous):
                tracking.data.update(latest_report_id=report.id, latest_report_at=stamp)
                self.store.put(tracking)
            label = aware(datetime.fromisoformat(stamp)).astimezone(AR).strftime("%d/%m/%Y %H:%M")
            location_url = "https://www.google.com/maps/search/?api=1&query=" + str(report.data['latitude']) + "," + str(report.data['longitude'])
            self.producer_update(trip, f"📍 Nueva ubicación informada por el chofer · {label} (Argentina).\n{location_url}", report.id)
            self.event("TRIP_LOCATION_RECORDED", report, "Punto de ubicación informado por el chofer")
            if cp.data['stage'] != "ARRIVAL" and trip.status == "IN_TRANSIT":
                self.schedule(trip.id, trip.test_run_id, "RECALCULATE", aware(self.clock()), suffix=report.id, report_id=report.id)
            return "✅ Ubicación registrada. La actualización quedó preparada para el productor."

    def driver_menu(self, phone, scope):
        rows = [r for r in self.store.list('tracking', scope) if r.data.get('driver_phone') == self.phone(phone)]
        trips = [self.trips.get(r.entity_id) for r in rows]
        trips = [t for t in trips if t and t.status == 'IN_TRANSIT']
        if not trips:
            return None
        actions = []
        for trip in trips[:3]:
            actions.extend((OutboundAction(id=f'trip-location:{trip.id}', label='📍 Compartir ubicación', value=f'/viaje {trip.id} ubicacion'),
                            OutboundAction(id=f'trip-arrival:{trip.id}', label='📍 Informar llegada', value=f'/viaje {trip.id} llegue'),
                            OutboundAction(id=f'trip-help:{trip.id}', label='💬 Necesito ayuda', value=f'/viaje {trip.id} ayuda')))
        return '🚚 Tenés un viaje en tránsito. Elegí qué querés informar.', tuple(actions)

    def action_command(self, action_id, phone, scope):
        if not action_id or not action_id.startswith(('trip-arrival:', 'trip-help:', 'trip-location:')):
            return None
        action, trip_id = action_id.split(':', 1)
        trip = self.trip(trip_id, scope)
        tracking = self.store.get(key('tracking', trip.id))
        if not tracking or tracking.data.get('driver_phone') != self.phone(phone):
            raise ValueError('El botón no pertenece al chofer de este viaje')
        return f"/viaje {trip.id} " + {'trip-arrival':'llegue','trip-help':'ayuda','trip-location':'ubicacion'}[action]

    def handle_text(self, text, phone, scope):
        parts = text.strip().split()
        if len(parts) == 3 and parts[0] == "/ubicacion" and parts[1] in {"origen", "destino"}:
            shipment = self.shipments.get(parts[2])
            if not shipment or shipment.test_run_id != scope or self.phone(shipment.producer_phone_number) != self.phone(phone):
                raise ValueError("La carga no pertenece a este productor o escenario")
            side = "origin" if parts[1] == "origen" else "destination"
            cp = RoutingEntry(kind="checkpoint", entity_id=shipment.id, test_run_id=scope, status="REQUESTED", data={"stage":"ACCESS", "phone":self.phone(phone), "location_id":getattr(shipment, side + "_location_id"), "side":side, "requested_at":aware(self.clock()).isoformat()})
            self.store.put(cp)
            if self.provider:
                result = self.provider.send_message(OutboundMessage(conversation_id=self.phone(phone), body="📍 Compartí el punto exacto del acceso de " + parts[1] + ".", message_type="location_request", allowlist_phone_number=self.phone(phone), correlation_id=cp.id, metadata={"checkpoint_id":cp.id,"qa_role":"Producer","qa_test_run_id":scope,"outbox_idempotency_key":cp.id,"entity_type":"ShipmentRequest","entity_id":shipment.id}))
                cp.data['provider_message_id'] = result.provider_message_id; self.store.put(cp)
            return "📍 Te pedí la ubicación del acceso. Compartí el punto y elegí el control si WhatsApp no lo cita automáticamente."
        if len(parts) == 3 and parts[0] == "/ubicacion":
            report, cp = self.store.get(parts[1]), self.store.get(parts[2])
            if not report or not cp or report.test_run_id != scope or cp.test_run_id != scope:
                raise ValueError("Control fuera del escenario activo")
            return self.link_report(report, cp, self.phone(phone))
        if len(parts) == 3 and parts[0] == "/viaje":
            trip = self.trip(parts[1], scope)
            tracking = self.store.get(key("tracking", trip.id))
            if not tracking or self.phone(phone) != tracking.data.get("driver_phone"):
                raise ValueError("Este WhatsApp no está confirmado como chofer del viaje")
            if trip.status != "IN_TRANSIT":
                raise ValueError("El viaje no está en tránsito")
            if parts[2].lower() == 'ubicacion':
                self.request_checkpoint(trip.id, scope, request_key=key('driver-request', str(int(aware(self.clock()).timestamp()) // 900)))
                return '📍 Te pedí compartir la ubicación actual para este viaje.'
            if parts[2].lower() in {"llegue", "llegué"}:
                self.cancel_jobs(trip.id, scope, "CHECKPOINT")
                for cp in self.store.list('checkpoint', scope, entity_id=trip.id):
                    if cp.data['stage'] != 'ARRIVAL' and cp.status in {'REQUESTED','OVERDUE'}:
                        cp.status = 'CANCELLED'; self.store.put(cp)
                self.event('TRIP_TRACKING_INCOMPLETE', tracking, 'Llegada informada: controles no recibidos quedan identificados')
                self.event("TRIP_ARRIVAL_REPORTED", tracking, "Chofer informó llegada; entrega pendiente de confirmar")
                self.request_checkpoint(trip.id, scope, "ARRIVAL")
                self.producer_update(trip, "📍 El chofer informó llegada. La entrega todavía debe confirmarse.", "arrival")
                return "📍 Llegada informada. Compartí tu ubicación para completar el control; la entrega se confirma por separado."
            if parts[2].lower() == "ayuda":
                self.event("TRIP_TRACKING_HELP_REQUESTED", tracking, "Chofer solicita ayuda a soporte")
                return "⚠️ Dejé tu solicitud de ayuda para soporte."
        return None

    def run_one(self):
        now = aware(self.clock())
        jobs = self.store.due(now)
        if not jobs:
            return None
        job = jobs[0]
        token = current_test_run_id.set(job.test_run_id)
        try:
            with self.store.lock("job:" + job.id):
                job = self.store.get(job.id)
                if job.status != "PENDING":
                    return "SKIPPED"
                if self.closed(job.test_run_id) and job.data.get("action") != "EXPIRE_ROUTE":
                    job.status = "CANCELLED"
                else:
                    try:
                        self._execute(job)
                        job.status = "DONE"
                    except (ValueError, RouteUnavailable) as exc:
                        job.status = "REVIEW"; job.data['error'] = str(exc)
                        self.event("ROUTE_JOB_REVIEW", job, "Tarea de recorrido requiere revisión")
                self.store.put(job)
                return job.status
        finally:
            current_test_run_id.reset(token)

    def _execute(self, job):
        action, scope = job.data['action'], job.test_run_id
        if action == "EXPAND":
            shipment = self.shipments.get(job.entity_id)
            if shipment and shipment.test_run_id == scope:
                self.publish(shipment, fallback=True)
            return
        tracking = self.store.get(key("tracking", job.entity_id))
        if action == "EXPIRE_ROUTE":
            if tracking and tracking.data.get("route_calculated_at") == job.data['version']:
                tracking.data.pop("route", None); tracking.data.pop("remaining_route", None); tracking.data['route_status'] = "EXPIRED"; self.store.put(tracking)
            return
        trip = self.trip(job.entity_id, scope)
        if trip.status in {"COMPLETED", "CANCELLED"}:
            return
        if action == "BEGIN_TRACKING":
            if trip.status == "IN_TRANSIT":
                self.begin_tracking(trip)
        elif action == "CHECKPOINT":
            if trip.status == "IN_TRANSIT":
                self.request_checkpoint(trip.id, scope, job.data['stage'])
        elif action in {"REMIND", "OVERDUE"}:
            cp = self.store.get(job.data['checkpoint_id'])
            if cp and cp.status == "REQUESTED":
                if action == "REMIND":
                    self.send_driver(tracking, "📍 Recordatorio: falta tu ubicación para el control del viaje.", "remind:" + cp.id, message_type="location_request", metadata={"checkpoint_id": cp.id})
                else:
                    cp.status = "OVERDUE"; self.store.put(cp)
                    self.event("TRIP_LOCATION_OVERDUE", cp, "Control pendiente: requiere atención de soporte")
        elif action == "RECALCULATE" and trip.status == "IN_TRANSIT":
            report = self.store.get(job.data['report_id'])
            if tracking.data.get('latest_report_id') != report.id:
                return
            points = tracking.data.get('points', [])
            if len(points) >= 2:
                # Keep every intermediate stop in declared order; do not infer passed stops.
                origin = {"label": "Última ubicación informada", "latitude": report.data['latitude'], "longitude": report.data['longitude']}
                route = self.calculate(tracking, [origin, *points[1:]], remaining=True)
                tracking.data['remaining_estimate'] = True; self.store.put(tracking)
                self.producer_update(trip, f"⏱️ Estimación restante orientativa: {int(route['duration_seconds']//60)} min de conducción, sin descansos. Calculada desde la última ubicación informada.", report.id + ":eta")

    def finish(self, trip):
        self.cancel_jobs(trip.id, trip.test_run_id)
        tracking = self.store.get(key('tracking', trip.id))
        if tracking:
            for cp in self.store.list('checkpoint', trip.test_run_id, entity_id=trip.id):
                if cp.status in {'REQUESTED','OVERDUE'}:
                    cp.status='CANCELLED';self.store.put(cp)
            self.event('TRIP_TRACKING_FINISHED', tracking, 'Seguimiento finalizado; controles faltantes conservados', received=sum(c.status == 'RECEIVED' for c in self.store.list('checkpoint', trip.test_run_id, entity_id=trip.id)))

    def tracking_view(self, trip_id, scope):
        trip = self.trip(trip_id, scope)
        entry = self.store.get(key("tracking", trip.id))
        data = dict(entry.data) if entry else {}
        if data.get('route_expires_at') and datetime.fromisoformat(data['route_expires_at']) <= aware(self.clock()):
            data.pop('route', None)
            data.pop('remaining_route', None)
        if not data.get('points'):
            try:
                data['points'] = self._route_points(trip)
            except ValueError:
                data['points'] = []
        data.pop('driver_phone', None)
        return {"trip_id": trip.id, "shipment_request_id": trip.shipment_request_id, "status": trip.status, "tracking": data,
                "checkpoints": [{**asdict(c), "data": {k:v for k,v in c.data.items() if k != "phone"}} for c in self.store.list("checkpoint", scope, entity_id=trip.id)],
                "reports": [{**asdict(r), "data": {k:v for k,v in r.data.items() if k != 'phone'}} for r in self.store.list("report", scope, entity_id=trip.id)]}

    def capture_preference(self, session, carrier, text):
        """Guided optional onboarding extension; same data validation as backoffice."""
        from app.domain.cargo import normalize_cargo_category
        normalized = fold_location(text)
        if normalized in {'mis recorridos', 'recorridos habituales'}:
            rows = self.store.list('preference', session.active_test_run_id, entity_id=carrier.id)
            actions = tuple(OutboundAction(id='pause:'+e.id, label=('Pausar ' if e.status == 'ACTIVE' else 'Activar ') + str(i+1), value=f'/recorrido {e.id} '+('pausar' if e.status == 'ACTIVE' else 'activar')) for i,e in enumerate(rows[:9]))
            body = '\n'.join(f"{i+1}. {e.data['points'][0]['label']} → {e.data['points'][-1]['label']} · {'Activo' if e.status == 'ACTIVE' else 'Pausado'}" for i,e in enumerate(rows[:9]))
            return '🛣️ Recorridos habituales:\n' + (body or 'Todavía no declaraste recorridos.') + '\nEscribí «agregar recorrido habitual» para registrar uno.', actions
        if text.startswith('/recorrido '):
            parts = text.split()
            row = self.store.get(parts[1]) if len(parts) == 3 else None
            if not row or row.kind != 'preference' or row.entity_id != carrier.id or row.test_run_id != session.active_test_run_id or parts[-1] not in {'pausar','activar'}:
                raise ValueError('Recorrido habitual no encontrado')
            row.status = 'PAUSED' if parts[-1] == 'pausar' else 'ACTIVE'; self.store.put(row)
            self.event('CARRIER_ROUTE_PREFERENCE_UPDATED', row, 'Preferencia actualizada por WhatsApp')
            return '✅ Recorrido habitual actualizado.', ()
        capture = session.route_availability_capture
        if normalized in {'agregar recorrido habitual', 'nuevo recorrido habitual', 'nuevo habitual'}:
            capture = {'kind':'preference', 'step':'origin', 'test_run_id':session.active_test_run_id}
            session.route_availability_capture = capture
            self.conversations.save(session)
            return '📍 ¿Cuál es el origen de tu recorrido habitual? Indicá localidad y provincia.', ()
        if capture.get('kind') != 'preference':
            return None
        if capture.get('test_run_id') != session.active_test_run_id:
            session.route_availability_capture = {}; self.conversations.save(session)
            return 'El escenario cambió. Iniciá un recorrido habitual nuevo.', ()
        if normalized in {'cancelar', 'salir'}:
            session.route_availability_capture = {}; self.conversations.save(session)
            return 'Registro de recorrido habitual cancelado.', ()
        step = capture['step']
        prompts = {'destination':'📍 ¿Cuál es el destino? Indicá localidad y provincia.',
                   'stops':'🛣️ Indicá las paradas en orden, separadas con punto y coma, o escribí «sin paradas».',
                   'cargo':'📦 ¿Transportás hacienda o granos? También podés indicar un tipo concreto de nuestro catálogo.',
                   'equipment':'🚚 ¿Qué equipo usás para este recorrido?',
                   'consent':'🔔 ¿Querés recibir oportunidades compatibles con este recorrido? Respondé sí o no.'}
        if step in {'origin','destination'}:
            capture[step] = self.node(text)['id']
            capture['step'] = 'destination' if step == 'origin' else 'stops'
        elif step == 'stops':
            capture['stops'] = [] if normalized == 'sin paradas' else [self.node(v.strip())['id'] for v in text.split(';') if v.strip()]
            capture['step'] = 'cargo'
        elif step == 'cargo':
            category, cargo = normalize_cargo_category(text, self.category_catalog), self.cargo_type(text)
            if not category and not cargo:
                return prompts['cargo'], ()
            capture['cargo_categories'] = [category] if category else []
            capture['cargo_types'] = [cargo] if cargo else []
            capture['step'] = 'equipment'
        elif step == 'equipment':
            if len(text.strip()) < 2 or len(text) > 100:
                return prompts['equipment'], ()
            capture['equipment_types'] = [normalize_equipment_or_declared(text)]
            capture['step'] = 'consent'
        elif step == 'consent':
            if normalized not in {'si','no'}:
                return prompts['consent'], ()
            capture['opt_in'] = normalized == 'si'
            capture['step'] = 'confirm'
        elif step == 'confirm':
            if normalized == 'editar':
                session.route_availability_capture = {}; self.conversations.save(session)
                return self.capture_preference(session, carrier, 'agregar recorrido habitual')
            if normalized not in {'confirmar','confirmo','si'}:
                return 'Elegí Confirmar o Editar.', ()
            self.save_preference(carrier.id, capture, session.active_test_run_id, actor='whatsapp')
            session.route_availability_capture = {}; self.conversations.save(session)
            return '✅ Recorrido habitual guardado. No representa disponibilidad libre; para eso elegí «Recorrido».', ()
        session.route_availability_capture = capture; self.conversations.save(session)
        if capture['step'] == 'confirm':
            nodes = [self.node(v)['label'] for v in [capture['origin'], *capture['stops'], capture['destination']]]
            return '🛣️ Confirmá tu recorrido habitual:\n' + ' → '.join(nodes) + '\n🔔 Avisos: ' + ('sí' if capture['opt_in'] else 'no'), (OutboundAction(id='pref-confirm', label='✅ Confirmar', value='confirmar'), OutboundAction(id='pref-edit', label='✏️ Editar', value='editar'))
        return prompts[capture['step']], ()
