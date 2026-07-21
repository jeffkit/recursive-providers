#!/usr/bin/env python3
"""
Sync providers.json from LiteLLM's model_prices_and_context_window.json.

Discovery model (strategy A — prefix-full + denoise):
  Instead of a hand-maintained allow-list of model names, every provider
  declares a LiteLLM key *prefix* (e.g. "gemini/", "deepseek/"). At sync
  time we walk LiteLLM's whole table, keep every key under that prefix that
  (a) carries input+output pricing and (b) passes the denoise filters, and
  group the results under the provider. This means newly published models
  show up automatically on the next daily run — no code change required.

  `PROVIDERS` below is the only hand-maintained part: it holds provider
  *shell* metadata (endpoint, key env, mainland reachability, the
  LiteLLM prefix, and a `preferred` ordering used to pick `default_model`).
  Model lists are fully derived.

Denoise filters (drop noise so `providers list` stays readable):
  - no input/output price -> skip (free/undocumented models)
  - non-text modalities -> skip (image/audio/embedding/realtime/tts)
  - experimental/preview/date-stamped builds -> skip
    (e.g. "-exp", "-preview", "-2025-01-25", "-0711-preview")
  - keys whose model name is just an upstream path with no clean short id
    (e.g. nested "meta-llama/..." under groq) -> still kept but the
    nested slash is preserved as the model name.

Usage:
  python3 scripts/sync_providers.py [--dry-run]
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

REPO_ROOT = Path(__file__).parent.parent
PROVIDERS_JSON = REPO_ROOT / "providers.json"

SOURCE_URL = "https://raw.githubusercontent.com/jeffkit/recursive-providers/main/providers.json"

# ---------------------------------------------------------------------------
# Provider shell registry — the only hand-maintained data.
#
# `litellm_provider` : the `litellm_provider` value LiteLLM stamps on this
#              vendor's models. We match on that field (not the key prefix)
#              because first-party vendors (OpenAI, Anthropic) publish models
#              under bare names ("gpt-4o", "claude-opus-4-8") with no prefix,
#              while others use "vendor/name". Matching on the provider tag
#              is unambiguous.
# `preferred`: ordered list of *LiteLLM keys*; the first one still present
#              after discovery becomes `default_model`. Lets us keep a
#              curated default even though the full model list is automatic.
# `manual`   : if True, the model list is left exactly as-is (not discovered
#              from LiteLLM) — used for local/free providers.
# ---------------------------------------------------------------------------
PROVIDERS: list[dict] = [
    {
        "id": "anthropic",
        "name": "Anthropic",
        "provider_type": "anthropic",
        "api_base": "https://api.anthropic.com",
        "anthropic_api_base": None,
        "mainland_accessible": False,
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "litellm_provider": "anthropic",
        "preferred": [
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-8",
            "anthropic/claude-haiku-4-5",
        ],
        "manual": False,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "provider_type": "openai",
        "api_base": "https://api.openai.com/v1",
        "anthropic_api_base": None,
        "mainland_accessible": False,
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "litellm_provider": "openai",
        "preferred": [
            "openai/gpt-5.5",
            "openai/gpt-5.4",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
        ],
        "manual": False,
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "provider_type": "openai",
        "api_base": "https://api.deepseek.com/v1",
        "anthropic_api_base": "https://api.deepseek.com/anthropic",
        "mainland_accessible": True,
        "key_env": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "litellm_provider": "deepseek",
        "preferred": [
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-reasoner",
        ],
        "manual": False,
    },
    {
        "id": "minimax",
        "name": "MiniMax",
        "provider_type": "openai",
        "api_base": "https://api.minimax.io/v1",
        "anthropic_api_base": None,
        "mainland_accessible": True,
        "key_env": "MINIMAX_API_KEY",
        "key_url": "https://www.minimax.io/user-center/basic-information",
        "litellm_provider": "minimax",
        "preferred": [
            "minimax/MiniMax-M3",
            "minimax/MiniMax-M2.7",
        ],
        "manual": False,
    },
    {
        "id": "zhipu",
        "name": "智谱 AI (GLM)",
        "provider_type": "openai",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "anthropic_api_base": None,
        "mainland_accessible": True,
        "key_env": "ZHIPU_API_KEY",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "litellm_provider": "zai",
        "preferred": [
            "zai/glm-5.1",
            "zai/glm-5",
            "zai/glm-4.7",
        ],
        "manual": False,
    },
    {
        "id": "moonshot",
        "name": "月之暗面 (Kimi)",
        "provider_type": "openai",
        "api_base": "https://api.moonshot.cn/v1",
        "anthropic_api_base": None,
        "mainland_accessible": True,
        "key_env": "MOONSHOT_API_KEY",
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "litellm_provider": "moonshot",
        "preferred": [
            "moonshot/kimi-k2.6",
            "moonshot/kimi-k2-thinking",
            "moonshot/moonshot-v1-128k",
        ],
        "manual": False,
    },
    {
        "id": "dashscope",
        "name": "阿里云通义千问",
        "provider_type": "openai",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "anthropic_api_base": None,
        "mainland_accessible": True,
        "key_env": "DASHSCOPE_API_KEY",
        "key_url": "https://dashscope.console.aliyun.com/apiKey",
        "litellm_provider": "dashscope",
        "preferred": [
            "dashscope/qwen-max",
            "dashscope/qwen-plus",
            "dashscope/qwen3-235b-a22b",
        ],
        "manual": False,
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "provider_type": "openai",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "anthropic_api_base": None,
        "mainland_accessible": False,
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        "litellm_provider": "gemini",
        "preferred": [
            "gemini/gemini-2.5-pro",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-3.5-flash",
        ],
        "manual": False,
    },
    {
        "id": "groq",
        "name": "Groq",
        "provider_type": "openai",
        "api_base": "https://api.groq.com/openai/v1",
        "anthropic_api_base": None,
        "mainland_accessible": False,
        "key_env": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "litellm_provider": "groq",
        "preferred": [
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant",
        ],
        "manual": False,
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "provider_type": "openai",
        "api_base": "https://api.mistral.ai/v1",
        "anthropic_api_base": None,
        "mainland_accessible": False,
        "key_env": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys/",
        "litellm_provider": "mistral",
        "preferred": [
            "mistral/mistral-large-latest",
            "mistral/mistral-small-latest",
            "mistral/codestral-latest",
        ],
        "manual": False,
    },
    {
        "id": "xai",
        "name": "xAI (Grok)",
        "provider_type": "openai",
        "api_base": "https://api.x.ai/v1",
        "anthropic_api_base": None,
        "mainland_accessible": False,
        "key_env": "XAI_API_KEY",
        "key_url": "https://console.x.ai/",
        "litellm_provider": "xai",
        "preferred": [
            "xai/grok-4.3",
            "xai/grok-build-0.1",
        ],
        "manual": False,
    },
    # Local/free provider — kept exactly as authored, never discovered.
    {
        "id": "ollama",
        "name": "Ollama (本地)",
        "provider_type": "openai",
        "api_base": "http://localhost:11434/v1",
        "anthropic_api_base": None,
        "mainland_accessible": True,
        "key_env": "",
        "key_url": "https://ollama.ai/",
        "litellm_provider": None,
        "preferred": [],
        "manual": True,
    },
]

# Keys (substrings) that mark non-text / experimental / date-stamped noise
# to skip. Covers image/video/audio/OCR models, fine-tunes, and snapshot
# builds carrying an 8-digit date stamp (e.g. "claude-opus-4-7-20260416").
_NOISE_RE = re.compile(
    r"(-exp\b|-preview\b|-\d{4}-\d{2}-\d{2}|-20\d{6}\b|-thinking-turbo\b|"
    r"image|img|video|dall-e|dall_e|sora|whisper|transcribe|tts|audio|realtime|"
    r"embedding|moderation|ocr|pixtral|instruct-[0-9]{4}\b|ft:|"
    r"/1792-|/1024-|/512-|/256-)",
    re.IGNORECASE,
)


def fetch_litellm() -> dict:
    print(f"Fetching {LITELLM_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(LITELLM_URL, timeout=30) as resp:
        return json.loads(resp.read())


def per_million(per_token: float | None) -> float | None:
    if per_token is None:
        return None
    return round(per_token * 1_000_000, 6)


# Model-name substrings that signal a non-text modality even when LiteLLM's
# capability flags are missing/empty. Belt-and-suspenders for is_text_model.
_NON_TEXT_NAME_RE = re.compile(
    r"(dall[-_]?e|sora|whisper|transcribe|tts|realtime|embedding|moderation|"
    r"pixtral|\bocr\b|image|video|audio)",
    re.IGNORECASE,
)


def is_text_model(lm: dict) -> bool:
    """Drop modalities we don't surface (image/audio/embedding/realtime)."""
    for cap in (
        "supported_openai_responses",
        "supported_openai_images",
        "supported_openai_audio",
        "supported_openai_embedding",
    ):
        if lm.get(cap):
            return False
    # Explicit non-text markers.
    if lm.get("mode") in ("embedding", "audio", "image") or lm.get("is_audio"):
        return False
    # Name-based fallback so known non-text models are dropped even when the
    # capability flags above are absent.
    name = (lm.get("model_name") or "").lower()
    if _NON_TEXT_NAME_RE.search(name):
        return False
    return True


def is_noise(key: str, lm: dict) -> bool:
    if _NOISE_RE.search(key):
        return True
    # Provider-internal routing aliases (e.g. "openai/", "azure/") that
    # merely re-expose another vendor's model under a generic prefix.
    if key.startswith(("openai/", "azure/", "azure_ai/")):
        return True
    return False


def build_model(key: str, lm: dict) -> dict:
    """Build a model entry from a LiteLLM record. `name` is the part after
    the provider prefix (kept verbatim, including any nested slash)."""
    name = key.split("/", 1)[1] if "/" in key else key
    model = {
        "name": name,
        "context_window": int(lm.get("max_input_tokens") or lm.get("max_tokens") or 0),
    }
    inp = per_million(lm.get("input_cost_per_token"))
    out = per_million(lm.get("output_cost_per_token"))
    if inp is not None and out is not None:
        pricing = {"input_per_million": inp, "output_per_million": out}
        cache = per_million(lm.get("cache_read_input_token_cost"))
        if cache is not None:
            pricing["cache_hit_input_per_million"] = cache
        model["pricing"] = pricing
    else:
        model["pricing"] = None
    return model


def discover_provider(meta: dict, litellm: dict) -> tuple[list[dict], list[str]]:
    """Return (models, change_notes) discovered for one provider.

    Matches on `litellm_provider` (the vendor tag LiteLLM stamps on each
    model) rather than the key prefix, so first-party vendors with bare model
    names (OpenAI's "gpt-4o", Anthropic's "claude-opus-4-8") are captured
    correctly. The model `name` is the key with the "vendor/" prefix stripped
    (a no-op for bare names).
    """
    provider = meta["litellm_provider"]
    prefix = f"{provider}/"
    models: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()

    for key, lm in litellm.items():
        if lm.get("litellm_provider") != provider:
            continue
        if is_noise(key, lm):
            continue
        if not is_text_model(lm):
            continue
        name = key[len(prefix):] if key.startswith(prefix) else key
        if name in seen:
            continue
        seen.add(name)
        model = build_model(key, lm)
        model["name"] = name
        models.append(model)
        notes.append(f"+{key}")

    # Stable, useful ordering: by context_window desc, then name.
    models.sort(key=lambda m: (m.get("context_window", 0), m["name"]), reverse=True)
    return models, notes


def pick_default_model(meta: dict, models: list[dict]) -> str:
    """First preferred key that survived discovery, else the largest model."""
    if meta.get("manual"):
        return meta.get("default_model", models[0]["name"] if models else "")
    names = {m["name"] for m in models}
    for pref in meta.get("preferred", []):
        pref_name = pref.split("/", 1)[1] if "/" in pref else pref
        if pref_name in names:
            return pref_name
    if models:
        return max(models, key=lambda m: m.get("context_window", 0))["name"]
    return ""


def sync(current: dict, litellm: dict) -> tuple[dict, list[str]]:
    all_changes: list[str] = []
    new_providers: list[dict] = []

    # Index current providers by id so manual providers (ollama) carry over
    # their authored model list and metadata untouched.
    cur_by_id = {p["id"]: p for p in current.get("providers", [])}

    for meta in PROVIDERS:
        pid = meta["id"]
        if meta.get("manual"):
            # Preserve the authored entry verbatim.
            cur = cur_by_id.get(pid)
            if cur is not None:
                new_providers.append(cur)
                continue
            # Fallback: reconstruct from meta (no models known).
            new_providers.append(_shell_entry(meta, [], meta.get("default_model", "")))
            continue

        models, notes = discover_provider(meta, litellm)
        default = pick_default_model(meta, models)
        entry = _shell_entry(meta, models, default)
        if notes:
            all_changes.append(f"{pid}: {len(notes)} model(s) synced")
        new_providers.append(entry)

    result = {
        "schema_version": current.get("schema_version", 1),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_url": SOURCE_URL,
        "providers": new_providers,
    }
    return result, all_changes


def _shell_entry(meta: dict, models: list[dict], default_model: str) -> dict:
    return {
        "id": meta["id"],
        "name": meta["name"],
        "provider_type": meta["provider_type"],
        "api_base": meta["api_base"],
        "anthropic_api_base": meta.get("anthropic_api_base"),
        "default_model": default_model,
        "models": models,
        "mainland_accessible": meta.get("mainland_accessible", False),
        "key_env": meta.get("key_env", ""),
        "key_url": meta.get("key_url", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without writing providers.json")
    args = parser.parse_args()

    current = json.loads(PROVIDERS_JSON.read_text())
    litellm = fetch_litellm()

    updated, changes = sync(current, litellm)

    if not changes and not args.dry_run:
        # Still bump updated_at so the 7-day cache TTL and freshness checks
        # reflect that a sync actually ran (even with no model deltas).
        updated["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        PROVIDERS_JSON.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
        )
        print("Sync ran; no model changes. Bumped updated_at.", file=sys.stderr)
        return

    print(f"{len(changes)} provider(s) updated:", file=sys.stderr)
    for c in changes:
        print(f"  {c}", file=sys.stderr)

    if args.dry_run:
        print("\n--- providers.json (dry run) ---")
        print(json.dumps(updated, ensure_ascii=False, indent=2))
    else:
        PROVIDERS_JSON.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
        )
        print("providers.json updated.", file=sys.stderr)


if __name__ == "__main__":
    main()
