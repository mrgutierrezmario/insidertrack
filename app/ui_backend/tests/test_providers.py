"""Provider cascade: Ollama, per-job preference, image routing and usage counters."""

import httpx
import pytest

from config import settings
from services import providers


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Start every test with no keys and a fresh usage table."""
    for k in ("anthropic_api_key", "gemini_api_key", "openai_api_key", "ollama_base_url", "ollama_vision_model"):
        monkeypatch.setattr(settings, k, "")
    monkeypatch.setattr(settings, "ai_provider", "claude")
    monkeypatch.setattr(settings, "ai_batch_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "llama3")
    providers._usage.clear()
    providers._usage_day["day"] = ""


def _ollama_ok(monkeypatch, text="OK", prompt_tokens=12, eval_tokens=3):
    calls = []

    def fake_post(self, url, json=None, **kw):
        calls.append((url, json))
        return httpx.Response(
            200, json={"response": text, "prompt_eval_count": prompt_tokens, "eval_count": eval_tokens},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return calls


def test_ollama_is_configured_by_url_not_key(monkeypatch):
    assert not providers.configured("ollama")
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434/")
    assert providers.configured("ollama")
    assert providers.key_for("ollama") == "http://ollama:11434"


def test_ollama_generates_and_counts_tokens(monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    calls = _ollama_ok(monkeypatch, text="Hello from llama")
    gen = providers.generate_text("hi", max_tokens=50, job="desk")
    assert gen.text == "Hello from llama"
    assert gen.provider == "ollama/llama3"
    assert (gen.input_tokens, gen.output_tokens) == (12, 3)
    url, body = calls[0]
    assert url == "http://ollama:11434/api/generate"
    assert body["stream"] is False and body["options"]["num_predict"] == 50
    row = providers.usage_snapshot()["jobs"]["desk"]["ollama"]
    assert row["calls"] == 1 and row["input_tokens"] == 12 and row["output_tokens"] == 3


def test_scheduled_job_prefers_ollama_over_the_chosen_cloud_provider(monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    _ollama_ok(monkeypatch)
    gen = providers.generate_text("brief", job="desk", prefer=providers.batch_provider())
    assert gen.provider.startswith("ollama/")
    assert gen.fallback is None  # ollama was first in line, so this is not a fallback


def test_ollama_failure_falls_through_to_the_cloud_provider(monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(settings, "ai_provider", "gemini")

    def fake_post(self, url, json=None, headers=None, **kw):
        if "11434" in url:
            raise httpx.ConnectError("refused")
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "cloud answer"}]}}],
                  "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    gen = providers.generate_text("brief", job="desk", prefer=providers.batch_provider())
    assert gen.provider.startswith("gemini/")
    assert gen.fallback == "ollama"
    assert gen.fallback_reason == "unavailable"
    jobs = providers.usage_snapshot()["jobs"]["desk"]
    assert jobs["ollama"]["failures"] == 1
    assert jobs["gemini"]["input_tokens"] == 100


def test_images_skip_ollama_unless_a_vision_model_is_set(monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "gemini_api_key", "g-key")
    assert providers._cascade("gemini", prefer="ollama", images=True) == ["gemini"]
    monkeypatch.setattr(settings, "ollama_vision_model", "llava")
    assert providers._cascade("gemini", prefer="ollama", images=True) == ["ollama", "gemini"]


def test_batch_provider_is_none_when_unconfigured():
    assert providers.batch_provider() is None


def test_usage_counters_reset_daily(monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    _ollama_ok(monkeypatch)
    providers.generate_text("a", job="notes")
    providers._usage_day["day"] = "1999-01-01"  # pretend a day passed
    providers.generate_text("b", job="notes")
    row = providers.usage_snapshot()["jobs"]["notes"]["ollama"]
    assert row["calls"] == 2 and row["calls_today"] == 1
