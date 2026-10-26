from pathlib import Path


class OpenAITranscriptionError(RuntimeError):
    pass


class OpenAITranscriptionClient:
    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key

    def transcribe(
        self,
        *,
        audio_path: Path,
        model: str,
        timeout_seconds: int,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAITranscriptionError("OpenAI package is not installed") from exc

        try:
            client = OpenAI(api_key=self._api_key, timeout=timeout_seconds)
            with audio_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                )
        except Exception as exc:  # noqa: BLE001
            raise OpenAITranscriptionError(f"OpenAI transcription failed: {exc.__class__.__name__}") from exc

        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise OpenAITranscriptionError("OpenAI transcription returned no text")
        return text
