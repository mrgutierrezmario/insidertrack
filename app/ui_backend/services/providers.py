"""Text generation behind one call, with the provider chosen in Settings.

Same shape as lecture-note-app's ``providers.py``: ``generate_text`` serves the
research notes, the Model Desk brief and the paper-filing reader; ``ai_provider``
picks Ollama (local, free), Claude (default), Gemini or OpenAI, and a failure
(bad key, quota, outage) falls through to whichever other providers are
configured. Scheduled jobs can prefer a different provider (``ai_batch_provider``)
so the free local model does the bulk work and the cloud keys are spent only
where they matter. Keys live in the ``app_settings`` table and are applied to
the live ``settings`` object by ``routers/app_settings.py``.

Claude goes through the official SDK; Ollama, Gemini and OpenAI are plain HTTP
via httpx, so there are no extra SDKs to carry. Every call is counted per job
and provider (``usage_snapshot``) so the Admin panel can show where the tokens go.
"""

import logging
import re
import time
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)

PROVIDERS = ("ollama", "claude", "gemini", "openai")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

LABELS = {"ollama": "Ollama (local)", "claude": "Claude", "gemini": "Gemini", "openai": "OpenAI"}
JOBS = ("notes", "desk", "vision", "test")


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
    input_tokens: int = 0    # as reported by the provider; 0 when unknown
    output_tokens: int = 0


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
    """The saved API key for a provider (empty string if none). Ollama has no
    key; its server URL plays the same role so the cascade code stays uniform."""
    return {
        "ollama": (settings.ollama_base_url or "").rstrip("/"),
        "claude": settings.anthropic_api_key or "",
        "gemini": settings.gemini_api_key or "",
        "openai": settings.openai_api_key or "",
    }.get(provider, "")


def model_for(provider: str) -> str:
    return {
        "ollama": settings.ollama_model,
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


def batch_provider() -> str | None:
    """The provider scheduled text jobs prefer, if it is configured."""
    chosen = settings.ai_batch_provider
    return chosen if chosen in PROVIDERS and configured(chosen) else None


# ── Usage accounting ──────────────────────────────────────────────────────────
# Per (job, provider) counters since the process started, plus today's slice,
# so the Admin panel can show which job is spending the tokens.

_usage: dict[str, dict[str, dict[str, int]]] = {}
_usage_day = {"day": ""}


def _record_usage(job: str, provider: str, gen: Generation | None, failed: bool, ms: int) -> None:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _usage_day["day"] != today:
        _usage_day["day"] = today
        for by_provider in _usage.values():
            for row in by_provider.values():
                row["calls_today"] = row["failures_today"] = 0
                row["input_tokens_today"] = row["output_tokens_today"] = 0
    row = _usage.setdefault(job, {}).setdefault(provider, {
        "calls": 0, "failures": 0, "input_tokens": 0, "output_tokens": 0, "ms": 0,
        "calls_today": 0, "failures_today": 0, "input_tokens_today": 0, "output_tokens_today": 0,
    })
    row["calls"] += 1
    row["calls_today"] += 1
    row["ms"] += ms
    if failed:
        row["failures"] += 1
        row["failures_today"] += 1
    elif gen is not None:
        row["input_tokens"] += gen.input_tokens
        row["output_tokens"] += gen.output_tokens
        row["input_tokens_today"] += gen.input_tokens
        row["output_tokens_today"] += gen.output_tokens
    logger.info(
        "ai_usage job=%s provider=%s ok=%s in=%d out=%d ms=%d",
        job, provider, not failed, gen.input_tokens if gen else 0, gen.output_tokens if gen else 0, ms,
    )


def usage_snapshot() -> dict:
    """Counters for the Admin panel: ``{job: {provider: {...}}}`` plus the day."""
    return {"day": _usage_day["day"], "jobs": {j: dict(p) for j, p in _usage.items()}}


# ── Implementations ───────────────────────────────────────────────────────────


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


def _ollama(prompt: str, max_tokens: int, timeout: float, key: str, model: str,
            images: list[bytes] | None = None) -> Generation:
    """Ollama's native API (``/api/generate``). ``key`` is the server URL.
    Images go to the vision model only when one is configured."""
    if images:
        model = settings.ollama_vision_model
        if not model:
            raise ProviderError("Ollama has no vision model configured")
    body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    }
    if images:
        body["images"] = [_b64(im) for im in images]
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{key}/api/generate", json=body)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Ollama unreachable at {key}: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise ProviderError(f"Ollama error {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = (data.get("response") or "").strip()
    if not text:
        raise ProviderError("Ollama returned no text")
    return Generation(
        text, f"ollama/{model}",
        input_tokens=int(data.get("prompt_eval_count") or 0),
        output_tokens=int(data.get("eval_count") or 0),
    )


def _claude(prompt: str, max_tokens: int, timeout: float, key: str, model: str,
            images: list[bytes] | None = None) -> Generation:
    from anthropic import Anthropic

    client = Anthropic(api_key=key, timeout=timeout, max_retries=1)
    content: list | str = prompt
    if images:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(im)}}
            for im in images
        ] + [{"type": "text", "text": prompt}]
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise ProviderError("Claude declined the request")
    text = "".join(getattr(b, "text", "") for b in response.content).strip()
    if not text:
        raise ProviderError("Claude returned no text")
    usage = getattr(response, "usage", None)
    return Generation(
        text, f"claude/{model}",
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


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


def _gemini(prompt: str, max_tokens: int, timeout: float, key: str, model: str,
            images: list[bytes] | None = None) -> Generation:
    url = GEMINI_URL.format(model=model)
    headers = {"x-goog-api-key": key}
    options = [_gemini_thinking_cfg[model]] if model in _gemini_thinking_cfg else list(_THINKING_OPTIONS)
    last = None
    parts = [{"inline_data": {"mime_type": "image/png", "data": _b64(im)}} for im in (images or [])] + [{"text": prompt}]
    with httpx.Client(timeout=timeout) as client:
        for cfg in options:
            body = {
                "contents": [{"role": "user", "parts": parts}],
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
            data = r.json()
            meta = data.get("usageMetadata") or {}
            return Generation(
                _gemini_text(data), f"gemini/{model}",
                input_tokens=int(meta.get("promptTokenCount") or 0),
                output_tokens=int(meta.get("candidatesTokenCount") or 0),
            )
    raise ProviderError(
        f"Gemini error {last.status_code if last else '?'}: {last.text[:300] if last else 'no response'}"
    )


def _openai(prompt: str, max_tokens: int, timeout: float, key: str, model: str,
            images: list[bytes] | None = None) -> Generation:
    content: list | str = prompt
    if images:
        content = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(im)}"}} for im in images] \
                  + [{"type": "text", "text": prompt}]
    with httpx.Client(timeout=timeout) as client:
        r = client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.1,
                "max_completion_tokens": max_tokens,
            },
        )
    if r.status_code != 200:
        raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise ProviderError("OpenAI returned no text")
    if not text:
        raise ProviderError("OpenAI returned no text")
    usage = data.get("usage") or {}
    return Generation(
        text, f"openai/{model}",
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )


_IMPL = {"ollama": _ollama, "claude": _claude, "gemini": _gemini, "openai": _openai}


def _run(provider: str, prompt: str, max_tokens: int, timeout: float, cred: Credential | None = None,
         images: list[bytes] | None = None) -> Generation:
    """Call one provider with either the visitor's credential or the site key."""
    if cred is not None:
        key, model = cred.key, cred.model or model_for(provider)
    else:
        key, model = key_for(provider), model_for(provider)
    if not key:
        raise ProviderError(f"No API key for {LABELS.get(provider, provider)}")
    if not model:
        raise ProviderError(f"No model set for {LABELS.get(provider, provider)}")
    return _IMPL[provider](prompt, max_tokens, timeout, key, model, images=images)


def _cascade(primary: str, *, prefer: str | None = None, images: bool = False) -> list[str]:
    """``prefer`` (if configured) first, then the chosen provider, then every
    other configured provider. Ollama is skipped for image requests unless a
    vision model is set — it would only fail and delay the real answer."""
    order = ([prefer] if prefer and configured(prefer) else []) + [primary]
    order += [p for p in PROVIDERS if configured(p)]
    seen: list[str] = []
    for p in order:
        if p in seen:
            continue
        if p == "ollama" and images and not settings.ollama_vision_model:
            continue
        seen.append(p)
    return seen


def _timed(job: str, provider: str, fn, *args, **kwargs) -> Generation:
    """Run one provider call and record it under ``job``."""
    started = time.monotonic()
    try:
        gen = fn(*args, **kwargs)
    except Exception:
        _record_usage(job, provider, None, True, int((time.monotonic() - started) * 1000))
        raise
    _record_usage(job, provider, gen, False, int((time.monotonic() - started) * 1000))
    return gen


def generate_text(
    prompt: str, *, max_tokens: int = 800, timeout: float = 60.0, cred: Credential | None = None,
    images: list[bytes] | None = None, job: str = "notes", prefer: str | None = None,
) -> Generation:
    """Generate with the configured provider, falling through to the other
    configured providers on failure. ``prefer`` puts one provider ahead of the
    chosen one (scheduled jobs pass ``batch_provider()`` so the free local model
    does the bulk work). With ``cred`` (a visitor's own key) only that provider
    is used — we never spend the site's keys on a request that brought its
    own, and never mix the two. ``job`` labels the call in the usage counters.
    Raises ProviderError when nothing is configured or everything failed."""
    if cred is not None:
        if cred.provider not in PROVIDERS:
            raise ProviderError("Unknown provider")
        return _timed(job, f"visitor:{cred.provider}", _run, cred.provider, prompt, max_tokens, timeout, cred, images=images)
    primary = active_provider()
    if primary is None:
        raise ProviderError("No AI provider configured")
    first_error: Exception | None = None
    order = _cascade(primary, prefer=prefer, images=bool(images))
    if not order:
        raise ProviderError("No provider can handle this request (images need a cloud key or an Ollama vision model)")
    for candidate in order:
        try:
            result = _timed(job, candidate, _run, candidate, prompt, max_tokens, timeout, images=images)
            if candidate != order[0]:
                result.fallback = order[0]
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
        return False, "No server URL saved" if provider == "ollama" else "No API key saved"
    try:
        g = _timed("test", provider, _run, provider, "Reply with the single word OK.", 16, 60.0, cred)
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


def list_claude_models(key: str | None = None) -> list[dict]:
    """Models the key can use, from Anthropic's Models API (newest first)."""
    from anthropic import Anthropic

    key = key or key_for("claude")
    if not key:
        raise ProviderError("No Claude API key saved")
    client = Anthropic(api_key=key, timeout=30.0, max_retries=1)
    out = []
    for m in client.models.list():
        out.append({"id": m.id, "label": getattr(m, "display_name", None) or m.id, "created": str(getattr(m, "created_at", "") or "")})
    out.sort(key=lambda x: x["created"], reverse=True)
    return [{"id": x["id"], "label": x["label"]} for x in out]


_OPENAI_EXCLUDE = ("embedding", "tts", "whisper", "dall-e", "realtime", "audio", "image", "transcribe", "moderation", "search", "davinci", "babbage", "codex", "computer-use")


def list_openai_models(key: str | None = None) -> list[dict]:
    """Chat-capable models the key can use, from OpenAI's live list (newest first)."""
    key = key or key_for("openai")
    if not key:
        raise ProviderError("No OpenAI API key saved")
    with httpx.Client(timeout=30.0) as client:
        r = client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:200]}")
    rows = []
    for m in r.json().get("data", []):
        mid = m.get("id", "")
        if not (mid.startswith("gpt-") or mid.startswith("o")):
            continue
        if any(x in mid for x in _OPENAI_EXCLUDE):
            continue
        rows.append({"id": mid, "label": mid, "created": m.get("created", 0)})
    rows.sort(key=lambda x: x["created"], reverse=True)
    return [{"id": x["id"], "label": x["label"]} for x in rows]


def list_ollama_models(url: str | None = None) -> list[dict]:
    """Models already pulled on the Ollama server (``/api/tags``)."""
    url = (url or key_for("ollama")).rstrip("/")
    if not url:
        raise ProviderError("No Ollama server URL saved")
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(f"{url}/api/tags")
    except httpx.HTTPError as exc:
        raise ProviderError(f"Ollama unreachable at {url}: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
    names = sorted(m.get("name", "") for m in r.json().get("models", []) if m.get("name"))
    return [{"id": n, "label": n} for n in names]


def list_models(provider: str, key: str | None = None) -> list[dict]:
    """Live model list for a provider (site key by default, or a visitor's)."""
    if provider == "ollama":
        return list_ollama_models(key)
    if provider == "claude":
        return list_claude_models(key)
    if provider == "gemini":
        return list_gemini_models(key)
    if provider == "openai":
        return list_openai_models(key)
    raise ProviderError("Unknown provider")
