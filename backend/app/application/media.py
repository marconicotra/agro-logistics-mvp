from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from app.domain.events import EventLog
from app.domain.models import Carrier, Document, Driver, MediaAsset, Message, Vehicle
from app.infrastructure.adapters.whatsapp import InboundMedia


T = TypeVar("T")


class Repository(Protocol, Generic[T]):
    def add(self, entity: T) -> T:
        pass

    def get(self, entity_id: str) -> T | None:
        pass

    def list(self, *, include_deleted: bool = False) -> list[T]:
        pass

    def save(self, entity: T) -> T:
        pass


class EventRecorder(Protocol):
    def record(
        self,
        *,
        event_type: str,
        actor_type: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        actor_id: str | None = None,
        related_entity_ids: dict[str, str] | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "system",
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> EventLog:
        pass


@dataclass(frozen=True)
class MediaProcessingResult:
    media_asset: MediaAsset
    document: Document | None
    events: tuple[EventLog, ...]


class MediaService:
    DOCUMENT_TYPES = {
        "dni": ("dni", "documento", "identidad"),
        "licencia": ("licencia", "registro"),
        "cedula": ("cedula", "cédula"),
        "seguro": ("seguro", "poliza", "póliza"),
        "vtv": ("vtv",),
        "rto": ("rto",),
        "cuit": ("cuit", "constancia"),
    }

    def __init__(
        self,
        *,
        media_assets: Repository[MediaAsset],
        documents: Repository[Document],
        messages: Repository[Message],
        carriers: Repository[Carrier],
        drivers: Repository[Driver] | None = None,
        vehicles: Repository[Vehicle] | None = None,
        event_log: EventRecorder,
        storage_dir: str = "var/media",
        download_enabled: bool = False,
        max_download_bytes: int = 10_000_000,
    ) -> None:
        self._media_assets = media_assets
        self._documents = documents
        self._messages = messages
        self._carriers = carriers
        self._drivers = drivers
        self._vehicles = vehicles
        self._event_log = event_log
        self._storage_dir = Path(storage_dir)
        self._download_enabled = download_enabled
        self._max_download_bytes = max_download_bytes

    def process_inbound_media(
        self,
        *,
        provider: str,
        media: InboundMedia,
        message: Message,
        phone_number: str | None,
        carrier_id: str | None,
        document_owner_type: str | None = None,
        document_owner_id: str | None = None,
        caption: str | None,
        correlation_id: str | None,
        idempotency_key: str,
    ) -> MediaProcessingResult:
        media_asset = self._media_assets.add(
            MediaAsset(
                message_id=message.id,
                provider=provider,
                provider_media_id=media.provider_media_id,
                media_type=media.media_type,
                mime_type=media.mime_type,
                file_name=media.file_name,
                external_url=media.external_url,
                sha256=media.sha256,
                status="RECEIVED",
            )
        )
        events: list[EventLog] = [
            self._event_log.record(
                event_type="MEDIA_ASSET_RECEIVED",
                actor_type=message.sender_type,
                entity_type="MediaAsset",
                entity_id=media_asset.id,
                summary="Media entrante registrada",
                related_entity_ids={
                    "messageId": message.id,
                    "conversationSessionId": message.conversation_session_id,
                },
                payload={
                    "provider_media_id": media.provider_media_id,
                    "media_type": media.media_type,
                    "mime_type": media.mime_type,
                    "file_name": media.file_name,
                    "has_external_url": bool(media.external_url),
                },
                source=provider,
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:media_received",
            )
        ]

        self.ensure_local_storage(media_asset)

        message.media_asset_id = media_asset.id
        message.message_type = self._message_type_for_media(media.media_type)
        message.related_entity_ids = {
            **message.related_entity_ids,
            "mediaAssetId": media_asset.id,
        }
        self._messages.save(message)

        if media.media_type == "audio":
            return MediaProcessingResult(media_asset=media_asset, document=None, events=tuple(events))

        # A phone match is not sufficient to identify the document owner: QA can
        # use one number for multiple roles, and a company contact may not be a driver.
        carrier = self._carriers.get(carrier_id) if carrier_id else None
        if carrier is None:
            events.append(
                self._event_log.record(
                    event_type="MEDIA_UNMATCHED_TO_CARRIER",
                    actor_type="SYSTEM",
                    entity_type="MediaAsset",
                    entity_id=media_asset.id,
                    summary="Media recibida sin transportista activo en el contexto",
                    related_entity_ids={"messageId": message.id},
                    payload={"phone_number_present": bool(phone_number)},
                    source="media_service",
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}:media_unmatched_carrier",
                )
            )
            return MediaProcessingResult(media_asset=media_asset, document=None, events=tuple(events))

        owner_type = (document_owner_type or "carrier").strip().lower()
        owner_id = document_owner_id or carrier.id
        if owner_type == "driver":
            owner = self._drivers.get(owner_id) if self._drivers is not None else None
            if owner is None or owner.carrier_id != carrier.id:
                owner_type = "invalid"
        elif owner_type == "vehicle":
            owner = self._vehicles.get(owner_id) if self._vehicles is not None else None
            if owner is None or owner.carrier_id != carrier.id:
                owner_type = "invalid"
        elif owner_type != "carrier" or owner_id != carrier.id:
            owner_type = "invalid"

        if owner_type == "invalid":
            events.append(
                self._event_log.record(
                    event_type="MEDIA_UNMATCHED_TO_CARRIER",
                    actor_type="SYSTEM",
                    entity_type="MediaAsset",
                    entity_id=media_asset.id,
                    summary="Media recibida con dueño no valido para el transportista activo",
                    related_entity_ids={"messageId": message.id, "carrierId": carrier.id},
                    payload={"phone_number_present": bool(phone_number)},
                    source="media_service",
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}:media_unmatched_owner",
                )
            )
            return MediaProcessingResult(media_asset=media_asset, document=None, events=tuple(events))

        inferred_type = self._infer_document_type(caption, media)
        if owner_type == "driver":
            inferred_type = "licencia"
        document = self._documents.add(
            Document(
                entity_type=owner_type,
                entity_id=owner_id,
                document_type=inferred_type,
                external_uri=media.external_url,
                provider=provider,
                provider_media_id=media.provider_media_id,
                mime_type=media.mime_type,
                file_name=media.file_name,
                storage_uri=media_asset.storage_uri,
                uploaded_by_phone=phone_number,
                status="PENDING",
                notes=caption,
            )
        )
        media_asset.status = "PROCESSED" if media_asset.status != "FAILED" else media_asset.status
        self._media_assets.save(media_asset)
        events.append(
            self._event_log.record(
                event_type="CARRIER_DOCUMENT_CREATED_FROM_MEDIA",
                actor_type="SYSTEM",
                entity_type="Document",
                entity_id=document.id,
                summary="Documento de transportista creado desde media",
                related_entity_ids={
                    "carrierId": carrier.id,
                    f"{owner_type}Id": owner_id,
                    "messageId": message.id,
                    "mediaAssetId": media_asset.id,
                },
                new_state=document.status,
                payload={
                    "document_type": document.document_type,
                    "provider_media_id": media.provider_media_id,
                    "mime_type": media.mime_type,
                    "file_name": media.file_name,
                },
                source="media_service",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:carrier_document_created",
            )
        )
        return MediaProcessingResult(media_asset=media_asset, document=document, events=tuple(events))

    def ensure_local_storage(
        self,
        media_asset: MediaAsset,
        *,
        force_download: bool = False,
        max_download_bytes: int | None = None,
    ) -> MediaAsset:
        if media_asset.storage_uri and Path(media_asset.storage_uri).exists():
            return media_asset
        if not (force_download or self._download_enabled):
            return media_asset
        self._download_media(media_asset, max_download_bytes=max_download_bytes)
        self._media_assets.save(media_asset)
        return media_asset

    def _download_media(self, media_asset: MediaAsset, *, max_download_bytes: int | None = None) -> None:
        if not media_asset.external_url:
            return
        parsed = urlparse(media_asset.external_url)
        if parsed.scheme not in {"http", "https"}:
            media_asset.status = "FAILED"
            media_asset.error_message = "Unsupported media URL scheme"
            return
        byte_limit = max_download_bytes or self._max_download_bytes
        try:
            request = Request(media_asset.external_url, headers={"user-agent": "agro-logistics-mvp/0.1"})
            with urlopen(request, timeout=10) as response:  # noqa: S310
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > byte_limit:
                    media_asset.status = "FAILED"
                    media_asset.error_message = "Media file exceeds max download size"
                    return
                data = response.read(byte_limit + 1)
                if len(data) > byte_limit:
                    media_asset.status = "FAILED"
                    media_asset.error_message = "Media file exceeds max download size"
                    return
        except (OSError, URLError, ValueError) as exc:
            media_asset.status = "FAILED"
            media_asset.error_message = f"Media download failed: {exc.__class__.__name__}"
            return

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        file_name = self._safe_file_name(media_asset)
        path = self._storage_dir / file_name
        path.write_bytes(data)
        media_asset.storage_uri = str(path)
        media_asset.status = "DOWNLOADED"

    def _safe_file_name(self, media_asset: MediaAsset) -> str:
        original = media_asset.file_name or f"{media_asset.id}.bin"
        suffix = Path(original).suffix[:16]
        return f"{media_asset.id}_{uuid4().hex}{suffix}"

    def _infer_document_type(self, caption: str | None, media: InboundMedia) -> str:
        haystack = " ".join(
            value.lower()
            for value in (caption, media.caption, media.file_name, media.mime_type)
            if value
        )
        for document_type, tokens in self.DOCUMENT_TYPES.items():
            if any(token in haystack for token in tokens):
                return document_type
        if media.media_type == "document":
            return "otros"
        return "unknown"

    def _message_type_for_media(self, media_type: str) -> str:
        if media_type in {"image", "audio", "document", "video"}:
            return media_type
        return "unknown"
