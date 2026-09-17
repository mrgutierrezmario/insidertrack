"""Text generation behind one call, with the provider chosen in Settings.

Same shape as lecture-note-app's ``providers.py``, minus Ollama: ``generate_text``
serves the research notes; ``ai_provider`` picks Claude (default), Gemini or
OpenAI, and a failure (bad key, quota, outage) falls through to whichever other
providers have a key saved. Keys live in the ``app_settings`` table and are
applied to the live ``settings`` object by ``routers/app_settings.py``.

Claude goes through the official SDK; Gemini and OpenAI are plain HTTP via
httpx, so there are no extra SDKs to carry.
"""

import logging
import re
import time
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)

PROVIDERS = ("claude", "gemini", "openai")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

LABELS = {"claude": "Claude", "gemini": "Gemini", "openai": "OpenAI"}


class ProviderError(Exception):
    """A provider refused or failed a request (bad key, quota, outage, empty reply)."""


@dataclass
class Credential:
    """A provider + key (+ optional model) supplied per request — a visitor's
    own key from their browser. Never stored server-side."""

    provider: str
    key: str
    model: str | None = None


@dataclass
class Generation:
    """A text result and the ``provider/model`` label that produced it.

    When the chosen provider failed and another answered instead, ``fallback``
    names the provider that failed and ``fallback_reason`` says why, in plain
    words for the UI.
    """

    text: str
    provider: str  # e.g. "claude/claude-opus-5"
    fallback: str | None = None
    fallback_reason: str | None = None


def describe_failure(exc: Exception | None) -> str:
    """Turn a provider exception into a short reason a user can act on."""
    if exc is None:
        return "unavailable"
    msg = str(exc)
    low = msg.lower()
    if "429" in msg or "quota" in low or "rate" in low:
        return "quota or rate limit exceeded"
    if "503" in msg or "overloaded" in low or "high demand" in low:
        return "temporarily overloaded"
    if "credit" in low:
        return "no API credits"
    if "401" in msg or "403" in msg or "api key" in low or "permission_denied" in low:
        return "API key rejected"
    if "404" in msg or "not found" in low:
        return "model not available"
    if "timeout" in low or "timed out" in low:
        return "timed out"
    return "unavailable"


def key_for(provider: str) -> str:
    """The saved API key for a provider (empty string if none)."""
    return {
        "claude": settings.anthropic_api_key or "",
        "gemini": settings.gemini_api_key or "",
        "openai": settings.openai_api_key or "",
    }.get(provider, "")


def model_for(provider: str) -> str:
    return {
        "claude": settings.claude_model,
        "gemini": settings.gemini_model,
        "openai": settings.openai_model,
    }.get(provider, "")


def configured(provider: str) -> bool:
    return bool(key_for(provider))


def configured_providers() -> list[str]:
    return [p for p in PROVIDERS if configured(p)]


def active_provider() -> str | None:
    """The provider research notes will actually use right now, or None if no
    key is saved anywhere."""
    chosen = settings.ai_provider if settings.ai_provider in PROVIDERS else "claude"
    if configured(chosen):
        return chosen
    others = configured_providers()
    if others:
        logger.warning("ai_provider=%s has no API key; using %s", chosen, others[0])
        return others[0]
    return None


# ── Implementations ───────────────────────────────────────────────────────────


def _claude(prompt: str, max_tokens: int, timeout: float, key: str, model: str) -> Generation:
    from anthropic import Anthropic

    client = Anthropic(api_key=key, timeout=timeout, max_retries=1)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise ProviderError("Claude declined the request")
    text = "".join(getattr(b, "text", "") for b in response.content).strip()
    if not text:
        raise ProviderError("Claude returned no text")
    return Generation(text, f"claude/{model}")


# Newer Gemini Flash models "think" before answering and bill it against
# maxOutputTokens, so a small budget returns nothing. We turn thinking off, but
# the accepted knob differs per model, so probe once and remember per model.
_THINKING_OPTIONS = (
    {"thinkingConfig": {"thinkingLevel": "MINIMAL"}},
    {"thinkingConfig": {"thinkingBudget": 0}},
    {},
)
_gemini_thinking_cfg: dict[str, dict] = {}


def _gemini_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        reason = (data.get("candidates") or [{}])[0].get("finishReason") or data.get(
            "promptFeedback", {}
        ).get("blockReason")
        raise ProviderError(f"Gemini returned no text (reason: {reason})")
    return text


def _gemini(prompt: str, max_tokens: int, timeout: float, key: str, model: str) -> Generation:
    url = GEMINI_URL.format(model=model)
    headers = {"x-goog-api-key": key}
    options = [_gemini_thinking_cfg[model]] if model in _gemini_thinking_cfg else list(_THINKING_OPTIONS)
    last = None
    with httpx.Client(timeout=timeout) as client:
        for cfg in options:
            body = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": max(max_tokens, 2048), **cfg},
            }
            for attempt in (1, 2):
                r = client.post(url, headers=headers, json=body)
                if r.status_code in (503, 429) and attempt == 1:
                    time.sleep(2)
                    continue
                break
            if r.status_code == 400 and cfg and ("thinking" in r.text.lower() or "invalid argument" in r.text.lower()):
                last = r
                continue  # this model doesn't take that knob; try the next
            if r.status_code != 200:
                raise ProviderError(f"Gemini error {r.status_code}: {r.text[:300]}")
            _gemini_thinking_cfg[model] = cfg
            return Generation(_gemini_text(r.json()), f"gemini/{model}")
    raise ProviderError(
        f"Gemini error {last.status_code if last else '?'}: {last.text[:300] if last else 'no response'}"
    )


def _openai(prompt: str, max_tokens: int, timeout: float, key: str, model: str) -> Generation:
    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_completion_tokens": max_tokens,
            },
        )
    if r.status_code != 200:
        raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    try:
        text = r.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise ProviderError("OpenAI returned no text")
    if not text:
        raise ProviderError("OpenAI returned no text")
    return Generation(text, f"openai/{model}")


_IMPL = {"claude": _claude, "gemini": _gemini, "openai": _openai}


def _run(provider: str, prompt: str, max_tokens: int, timeout: float, cred: Credential | None = None) -> Generation:
    """Call one provider with either the visitor's credential or the site key."""
    if cred is not None:
        key, model = cred.key, cred.model or model_for(provider)
    else:
        key, model = key_for(provider), model_for(provider)
    if not key:
        raise ProviderError(f"No API key for {LABELS.get(provider, provider)}")
    if not model:
        raise ProviderError(f"No model set for {LABELS.get(provider, provider)}")
    return _IMPL[provider](prompt, max_tokens, timeout, key, model)


def _cascade(primary: str) -> list[str]:
    """The chosen provider first, then every other provider with a key saved."""
    return [primary] + [p for p in PROVIDERS if p != primary and configured(p)]


def generate_text(
    prompt: str, *, max_tokens: int = 800, timeout: float = 60.0, cred: Credential | None = None
) -> Generation:
    """Generate with the configured provider, falling through to the other
    configured providers on failure. With ``cred`` (a visitor's own key) only
    that provider is used — we never spend the site's keys on a request that
    brought its own, and never mix the two. Raises ProviderError when nothing
    is configured or everything failed."""
    if cred is not None:
        if cred.provider not in PROVIDERS:
            raise ProviderError("Unknown provider")
        return _run(cred.provider, prompt, max_tokens, timeout, cred)
    primary = active_provider()
    if primary is None:
        raise ProviderError("No AI provider configured")
    first_error: Exception | None = None
    for candidate in _cascade(primary):
        try:
            result = _run(candidate, prompt, max_tokens, timeout)
            if candidate != primary:
                result.fallback = primary
                result.fallback_reason = describe_failure(first_error)
            return result
        except Exception as e:  # noqa: BLE001 — try the next provider
            first_error = first_error or e
            logger.warning("%s failed (%s: %s) — trying next provider", candidate, type(e).__name__, str(e)[:200])
    raise ProviderError(f"All providers failed: {describe_failure(first_error)}")


def test_provider(provider: str, cred: Credential | None = None) -> tuple[bool, str]:
    """Cheap connectivity check used by the Settings panels (site key or a visitor's)."""
    if provider not in PROVIDERS:
        return False, "Unknown provider"
    if cred is None and not configured(provider):
        return False, "No API key saved"
    try:
        g = _run(provider, "Reply with the single word OK.", 16, 30.0, cred)
        return True, f"Connected ({g.provider})"
    except Exception as e:  # noqa: BLE001 — reported to the UI
        return False, f"{type(e).__name__}: {str(e)[:200]}"


# ── Model discovery ───────────────────────────────────────────────────────────

_EXCLUDE = ("image", "tts", "customtools", "deep-research", "lyria", "omni", "embedding", "aqa", "live", "audio")


def list_gemini_models(key: str | None = None) -> list[dict]:
    """Chat-capable Gemini models this key can use, newest first, from Google's
    live list — so the Settings dropdown never goes stale."""
    key = key or key_for("gemini")
    if not key:
        raise ProviderError("No Gemini API key saved")
    with httpx.Client(timeout=30.0) as client:
        r = client.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": key}, params={"pageSize": 200})
    if r.status_code != 200:
        raise ProviderError(f"Gemini error {r.status_code}: {r.text[:200]}")
    out = []
    for m in r.json().get("models", []):
        name = m.get("name", "").replace("models/", "")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if not name.startswith("gemini-") or not ("flash" in name or "pro" in name):
            continue
        if any(x in name for x in _EXCLUDE):
            continue
        out.append({"id": name, "label": m.get("displayName") or name})

    # Aliases first (they auto-track the newest release), then newest version numbers.
    def sort_key(item):
        n = item["id"]
        if "latest" in n:
            return (0, 0.0, False, n)
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return (1, -float(v.group(1)) if v else 0.0, "preview" in n, n)

    out.sort(key=sort_key)
    return out
