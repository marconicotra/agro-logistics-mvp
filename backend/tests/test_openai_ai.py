from decimal import Decimal
import json
import sys
from types import SimpleNamespace

import pytest

from app.application.ai import AIExtractionError
from app.api.dependencies import get_ai_extraction_client
from app.core.config import get_settings
from app.infrastructure.adapters.openai_ai import OpenAIExtractionClient


def test_openai_extraction_maps_structured_fields_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "origin": "Pergamino",
                                    "destination": "Rosario",
                                    "date_window_start": "2026-10-02T00:00:00",
                                    "date_window_end": None,
                                    "livestock_type": "novillos",
                                    "quantity_estimate": "30",
                                    "contact": None,
                                    "confidence": "high",
                                    "has_ambiguous_location": False,
                                    "field_confidence": {"origin": "high"},
                                }
                            )
                        )
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):  # noqa: ANN003
            captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    result = OpenAIExtractionClient(api_key="test-only", model="gpt-4.1-mini").extract_load_data(
        "30 novillos de Pergamino a Rosario el viernes"
    )

    assert result.origin == "Pergamino"
    assert result.destination == "Rosario"
    assert result.livestock_type == "novillos"
    assert result.quantity_estimate == Decimal("30")
    assert result.date_window_start is not None
    assert captured["model"] == "gpt-4.1-mini"
    assert captured["response_format"] == {"type": "json_object"}
    assert "No infieras quantity_unit" in captured["messages"][0]["content"]


def test_openai_extraction_redacts_provider_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.fail))

        @staticmethod
        def fail(**kwargs):  # noqa: ANN003, ANN201
            raise RuntimeError("private-provider-detail")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    client = OpenAIExtractionClient(api_key="test-only", model="gpt-4.1-mini")

    with pytest.raises(AIExtractionError, match="RuntimeError") as error:
        client.extract_load_data("mensaje privado")

    assert "private-provider-detail" not in str(error.value)
    assert "mensaje privado" not in str(error.value)


def test_openai_extraction_maps_grain_cargo(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompletions:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                    "cargo_category": "GRAIN",
                    "cargo_type": "soja",
                    "quantity_unit": "toneladas",
                    "quantity_estimate": "13",
                    "confidence": "high",
                })))],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    result = OpenAIExtractionClient(api_key="test-only", model="gpt-4.1-mini").extract_load_data(
        "13 toneladas de soja"
    )

    assert result.cargo_category == "GRAIN"
    assert result.cargo_type == "soja"
    assert result.quantity_unit == "TON"
    assert result.quantity_estimate == Decimal("13")


def test_ai_dependency_uses_backend_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-only")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    get_settings.cache_clear()

    client = get_ai_extraction_client()

    assert isinstance(client, OpenAIExtractionClient)
    assert client._model == "gpt-test"
