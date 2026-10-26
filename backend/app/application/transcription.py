from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from app.domain.events import EventLog
from app.domain.models import MediaAsset


T = TypeVar("T")


class Repository(Protocol, Generic[T]):
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


class SpeechToTextClient(Protocol):
    def transcribe(
        self,
        *,
        audio_path: Path,
        model: str,
        timeout_seconds: int,
    ) -> str:
        pass


class MediaFileResolver(Protocol):
    def ensure_local_storage(
        self,
        media_asset: MediaAsset,
        *,
        force_download: bool = False,
        max_download_bytes: int | None = None,
    ) -> MediaAsset:
        pass


@dataclass(frozen=True)
class TranscriptionResult:
    status: str
    text: str | None = None
    error: str | None = None
    media_asset: MediaAsset | None = None
    events: tuple[EventLog, ...] = ()


class TranscriptionService:
    def __init__(
        self,
        *,
        media_assets: Repository[MediaAsset],
        event_log: EventRecorder,
        media_file_resolver: MediaFileResolver,
        stt_client: SpeechToTextClient | None,
        enabled: bool,
        provider: str,
        model: str,
        timeout_seconds: int,
        max_audio_bytes: int,
    ) -> None:
        self._media_assets = media_assets
        self._event_log = event_log
        self._media_file_resolver = media_file_resolver
        self._stt_client = stt_client
        self._enabled = enabled
        self._provider = provider
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_audio_bytes = max_audio_bytes

    def transcribe_media_asset(
        self,
        *,
        media_asset: MediaAsset,
        correlation_id: str | None,
        idempotency_key: str,
        related_entity_ids: dict[str, str] | None = None,
    ) -> TranscriptionResult:
        related = related_entity_ids or {}
        if media_asset.media_type != "audio":
            media_asset.transcription_status = "NOT_REQUIRED"
            media_asset.transcription_provider = None
            media_asset.transcription_model = None
            media_asset.transcription_error = None
            self._media_assets.save(media_asset)
            return TranscriptionResult(status="NOT_REQUIRED", media_asset=media_asset)

        media_asset.transcription_provider = self._provider
        media_asset.transcription_model = self._model

        if not self._enabled:
            return self._skip(
                media_asset=media_asset,
                reason="speech_to_text_disabled",
                summary="Transcripcion de audio omitida",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_skipped",
                related_entity_ids=related,
            )

        if self._stt_client is None:
            return self._fail(
                media_asset=media_asset,
                error="Speech-to-text client is not configured",
                summary="Fallo de configuracion de transcripcion",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                previous_state=media_asset.transcription_status,
            )

        previous_status = media_asset.transcription_status
        media_asset.transcription_status = "PENDING"
        media_asset.transcription_error = None
        media_asset.transcription_text = None
        self._media_assets.save(media_asset)
        started_event = self._event_log.record(
            event_type="MEDIA_TRANSCRIPTION_STARTED",
            actor_type="SYSTEM",
            entity_type="MediaAsset",
            entity_id=media_asset.id,
            summary="Transcripcion de audio iniciada",
            related_entity_ids=related,
            previous_state=previous_status,
            new_state=media_asset.transcription_status,
            payload={
                "provider": self._provider,
                "model": self._model,
            },
            source="transcription_service",
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}:transcription_started",
        )

        try:
            self._media_file_resolver.ensure_local_storage(
                media_asset,
                force_download=True,
                max_download_bytes=self._max_audio_bytes,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(
                media_asset=media_asset,
                error=f"Audio download failed: {exc.__class__.__name__}",
                summary="Fallo al descargar audio para transcripcion",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                existing_events=(started_event,),
            )

        if not media_asset.storage_uri:
            return self._fail(
                media_asset=media_asset,
                error="Audio file is not available locally",
                summary="Audio sin archivo local para transcripcion",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                existing_events=(started_event,),
            )

        audio_path = Path(media_asset.storage_uri)
        if not audio_path.exists():
            return self._fail(
                media_asset=media_asset,
                error="Stored audio file does not exist",
                summary="Archivo de audio local inexistente",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                existing_events=(started_event,),
            )

        file_size = audio_path.stat().st_size
        if file_size > self._max_audio_bytes:
            return self._fail(
                media_asset=media_asset,
                error="Audio file exceeds max transcription size",
                summary="Audio excede tamano maximo de transcripcion",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                existing_events=(started_event,),
                payload={"file_size_bytes": file_size},
            )

        try:
            text = self._stt_client.transcribe(
                audio_path=audio_path,
                model=self._model,
                timeout_seconds=self._timeout_seconds,
            ).strip()
        except Exception as exc:  # noqa: BLE001
            return self._fail(
                media_asset=media_asset,
                error=str(exc),
                summary="Fallo al transcribir audio",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                existing_events=(started_event,),
            )

        if not text:
            return self._fail(
                media_asset=media_asset,
                error="Transcription returned empty text",
                summary="Transcripcion vacia",
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:transcription_failed",
                related_entity_ids=related,
                existing_events=(started_event,),
            )

        media_asset.transcription_status = "SUCCEEDED"
        media_asset.transcription_text = text
        media_asset.transcription_error = None
        media_asset.transcribed_at = datetime.now(UTC)
        self._media_assets.save(media_asset)
        succeeded_event = self._event_log.record(
            event_type="MEDIA_TRANSCRIPTION_SUCCEEDED",
            actor_type="SYSTEM",
            entity_type="MediaAsset",
            entity_id=media_asset.id,
            summary="Audio transcripto correctamente",
            related_entity_ids=related,
            previous_state="PENDING",
            new_state=media_asset.transcription_status,
            payload={
                "provider": self._provider,
                "model": self._model,
                "text_length": len(text),
            },
            source="transcription_service",
            correlation_id=correlation_id,
            idempotency_key=f"{idempotency_key}:transcription_succeeded",
        )
        return TranscriptionResult(
            status=media_asset.transcription_status,
            text=text,
            media_asset=media_asset,
            events=(started_event, succeeded_event),
        )

    def _skip(
        self,
        *,
        media_asset: MediaAsset,
        reason: str,
        summary: str,
        correlation_id: str | None,
        idempotency_key: str,
        related_entity_ids: dict[str, str],
    ) -> TranscriptionResult:
        previous_status = media_asset.transcription_status
        media_asset.transcription_status = "SKIPPED"
        media_asset.transcription_error = reason
        media_asset.transcription_text = None
        self._media_assets.save(media_asset)
        event = self._event_log.record(
            event_type="MEDIA_TRANSCRIPTION_SKIPPED",
            actor_type="SYSTEM",
            entity_type="MediaAsset",
            entity_id=media_asset.id,
            summary=summary,
            related_entity_ids=related_entity_ids,
            previous_state=previous_status,
            new_state=media_asset.transcription_status,
            payload={
                "reason": reason,
                "provider": self._provider,
                "model": self._model,
            },
            source="transcription_service",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return TranscriptionResult(
            status=media_asset.transcription_status,
            error=reason,
            media_asset=media_asset,
            events=(event,),
        )

    def _fail(
        self,
        *,
        media_asset: MediaAsset,
        error: str,
        summary: str,
        correlation_id: str | None,
        idempotency_key: str,
        related_entity_ids: dict[str, str],
        existing_events: tuple[EventLog, ...] = (),
        payload: dict[str, Any] | None = None,
        previous_state: str = "PENDING",
    ) -> TranscriptionResult:
        media_asset.transcription_status = "FAILED"
        media_asset.transcription_text = None
        media_asset.transcription_error = error
        self._media_assets.save(media_asset)
        event = self._event_log.record(
            event_type="MEDIA_TRANSCRIPTION_FAILED",
            actor_type="SYSTEM",
            entity_type="MediaAsset",
            entity_id=media_asset.id,
            summary=summary,
            related_entity_ids=related_entity_ids,
            previous_state=previous_state,
            new_state=media_asset.transcription_status,
            payload={
                "error": error,
                "provider": self._provider,
                "model": self._model,
                **(payload or {}),
            },
            source="transcription_service",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return TranscriptionResult(
            status=media_asset.transcription_status,
            error=error,
            media_asset=media_asset,
            events=existing_events + (event,),
        )
