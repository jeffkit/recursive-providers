#!/usr/bin/env python3
"""
Sync providers.json from LiteLLM's model_prices_and_context_window.json.

Providers covered by LiteLLM (auto-synced):
  anthropic, openai, deepseek, minimax, zhipu, moonshot, dashscope,
  gemini, groq, mistral, xai

Providers NOT in LiteLLM (kept as-is from current providers.json):
  ollama

Usage:
  python3 scripts/sync_providers.py [--dry-run]
"""

import argparse
import json
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

# ---------------------------------------------------------------------------
# Mapping: our model name -> LiteLLM key
#
# Format: { our_model_name: litellm_key }
# LiteLLM keys use "provider/model" format; costs are per-token (multiply by
# 1_000_000 to get per-million).
# ---------------------------------------------------------------------------
MODEL_MAP: dict[str, str] = {
    # Anthropic
    "claude-opus-4-8":    "claude-opus-4-8",
    "claude-opus-4-7":    "claude-opus-4-7",
    "claude-sonnet-4-6":  "claude-sonnet-4-6",
    "claude-haiku-4-5":   "claude-haiku-4-5-20251001",
    # OpenAI
    "gpt-5.5":            "gpt-5.5",
    "gpt-5.4":            "gpt-5.4",
    "gpt-5.4-mini":       "gpt-5.4-mini",
    "gpt-4o":             "gpt-4o",
    "gpt-4o-mini":        "gpt-4o-mini",
    "o3":                 "o3",
    "o4-mini":            "o4-mini",
    # DeepSeek
    "deepseek-v4-flash":  "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro":    "deepseek/deepseek-v4-pro",
    "deepseek-chat":      "deepseek/deepseek-chat",
    "deepseek-reasoner":  "deepseek/deepseek-reasoner",
    # MiniMax
    "MiniMax-M3":         "minimax/MiniMax-M3",
    "MiniMax-M2.7":       "minimax/MiniMax-M2.7",
    # Zhipu GLM (LiteLLM uses "zai/" prefix)
    "glm-5.1":            "zai/glm-5.1",
    "glm-5":              "zai/glm-5",
    "glm-4.7":            "zai/glm-4.7",
    "glm-4.7-flash":      "zai/glm-4.7-flash",
    # Moonshot
    "kimi-k2.6":          "moonshot/kimi-k2.6",
    "moonshot-v1-128k":   "moonshot/moonshot-v1-128k",
    "moonshot-v1-8k":     "moonshot/moonshot-v1-8k",
    # DashScope / Qwen
    "qwen-max":           "dashscope/qwen-max",
    "qwen3-235b-a22b":    "dashscope/qwen3-235b-a22b",
    "qwen3-32b":          "dashscope/qwen3-32b",
    "qwen-plus":          "dashscope/qwen-plus",
    # Gemini
    "gemini-3.5-flash":         "gemini/gemini-3.5-flash",
    "gemini-3.1-pro-preview":   "gemini/gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite":    "gemini/gemini-3.1-flash-lite",
    "gemini-2.5-pro":           "gemini/gemini-2.5-pro",
    "gemini-2.5-flash":         "gemini/gemini-2.5-flash",
    "gemini-2.5-flash-lite":    "gemini/gemini-2.5-flash-lite",
    # Groq
    "llama-3.3-70b-versatile":              "groq/llama-3.3-70b-versatile",
    "llama-3.1-8b-instant":                 "groq/llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct": "groq/meta-llama/llama-4-scout-17b-16e-instruct",
    "moonshotai/kimi-k2-instruct":          "groq/moonshotai/kimi-k2-instruct",
    # Mistral
    "mistral-large-latest": "mistral/mistral-large-latest",
    "mistral-small-latest": "mistral/mistral-small-latest",
    "codestral-latest":     "mistral/codestral-latest",
    # xAI
    "grok-4.3":       "xai/grok-4.3",
    "grok-build-0.1": "xai/grok-build-0.1",
}

# Providers whose models are NOT in LiteLLM — keep unchanged.
MANUAL_PROVIDER_IDS = {"ollama"}


def fetch_litellm() -> dict:
    print(f"Fetching {LITELLM_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(LITELLM_URL, timeout=30) as resp:
        return json.loads(resp.read())


def per_million(per_token: float | None) -> float | None:
    if per_token is None:
        return None
    return round(per_token * 1_000_000, 6)


def build_pricing(lm: dict) -> dict | None:
    inp = per_million(lm.get("input_cost_per_token"))
    out = per_million(lm.get("output_cost_per_token"))
    if inp is None or out is None:
        return None
    pricing: dict = {"input_per_million": inp, "output_per_million": out}
    cache = per_million(lm.get("cache_read_input_token_cost"))
    if cache is not None:
        pricing["cache_hit_input_per_million"] = cache
    return pricing


def update_model(model: dict, litellm_data: dict) -> tuple[dict, list[str]]:
    """Return updated model dict and list of change descriptions."""
    name = model["name"]
    lm_key = MODEL_MAP.get(name)
    changes: list[str] = []

    if lm_key is None or lm_key not in litellm_data:
        # No LiteLLM entry — keep as-is
        return model, changes

    lm = litellm_data[lm_key]
    updated = dict(model)

    # context_window
    lm_ctx = lm.get("max_input_tokens") or lm.get("max_tokens")
    if lm_ctx and lm_ctx != model.get("context_window"):
        changes.append(f"{name}: context_window {model.get('context_window')} -> {lm_ctx}")
        updated["context_window"] = lm_ctx

    # pricing (skip models with null pricing, e.g. ollama)
    if model.get("pricing") is not None:
        new_pricing = build_pricing(lm)
        if new_pricing and new_pricing != model.get("pricing"):
            changes.append(f"{name}: pricing updated")
            updated["pricing"] = new_pricing

    return updated, changes


def sync(current: dict, litellm_data: dict) -> tuple[dict, list[str]]:
    all_changes: list[str] = []
    new_providers = []

    for provider in current["providers"]:
        if provider["id"] in MANUAL_PROVIDER_IDS:
            new_providers.append(provider)
            continue

        new_models = []
        for model in provider["models"]:
            updated_model, changes = update_model(model, litellm_data)
            new_models.append(updated_model)
            all_changes.extend(changes)

        new_provider = dict(provider)
        new_provider["models"] = new_models
        new_providers.append(new_provider)

    result = dict(current)
    result["providers"] = new_providers
    result["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return result, all_changes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print changes without writing providers.json")
    args = parser.parse_args()

    current = json.loads(PROVIDERS_JSON.read_text())
    litellm_data = fetch_litellm()

    updated, changes = sync(current, litellm_data)

    if not changes:
        print("No changes detected.", file=sys.stderr)
        if not args.dry_run:
            # Still update updated_at so the file reflects the check date
            PROVIDERS_JSON.write_text(
                json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
            )
        return

    print(f"{len(changes)} change(s):", file=sys.stderr)
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
