#!/usr/bin/env python3
"""
Validate providers.json structure and pricing sanity.

Checks (beyond JSON syntax):
  - top-level: schema_version == 1, updated_at is an RFC 3339 UTC stamp,
    providers is a non-empty list of unique ids
  - every provider: provider_type in (openai, anthropic), non-empty models
  - every model: non-empty name, unique within the provider, context_window
    int >= 0, pricing null or non-negative numbers
  - provider.default_model must exist in models[] and carry pricing —
    unless the provider is key-less/local (empty `key_env`, e.g. ollama),
    where null pricing is legitimate

The default_model checks exist because the catalog once drifted for two
months unnoticed (jeffkit/recursive-providers#3): `deepseek-flash` was
missing entirely and a provider's main model carried stale pricing —
neither would have passed here.

  - with --max-age-days N: `updated_at` must be no older than N days —
    used by the scheduled validate run to catch a stalled sync (the
    two-month silent drift of #3 showed up as a stale `updated_at`)

Usage:
  python3 scripts/validate_providers.py [path] [--max-age-days N]
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

PRICING_KEYS = {"input_per_million", "output_per_million", "cache_hit_input_per_million"}


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def check_number(pid: str, name: str, key: str, value) -> None:
    # bool is an int subclass — exclude it explicitly.
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        fail(f"{pid}/{name}: {key} must be a non-negative number, got {value!r}")


def check_pricing(pid: str, name: str, pricing) -> None:
    if pricing is None:
        return
    if not isinstance(pricing, dict):
        fail(f"{pid}/{name}: pricing must be an object or null")
    for key in ("input_per_million", "output_per_million"):
        if key not in pricing:
            fail(f"{pid}/{name}: pricing.{key} is required")
        check_number(pid, name, f"pricing.{key}", pricing[key])
    if "cache_hit_input_per_million" in pricing:
        check_number(pid, name, "pricing.cache_hit_input_per_million",
                     pricing["cache_hit_input_per_million"])
    extra = set(pricing) - PRICING_KEYS
    if extra:
        fail(f"{pid}/{name}: unexpected pricing keys: {sorted(extra)}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=None,
                        help="providers.json path (default: repo root)")
    parser.add_argument("--max-age-days", type=int, default=0,
                        help="fail if updated_at is older than N days (0 = skip)")
    args = parser.parse_args()

    path = (Path(args.path) if args.path
            else Path(__file__).parent.parent / "providers.json")
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        fail(f"{path.name}: cannot parse JSON: {e}")

    if data.get("schema_version") != 1:
        fail("schema_version must be 1")
    updated_at = data.get("updated_at")
    if not updated_at or not RFC3339_RE.match(str(updated_at)):
        fail(f"updated_at must be an RFC 3339 UTC timestamp, got {updated_at!r}")
    if args.max_age_days > 0:
        synced = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - synced).total_seconds() / 86400
        if age_days > args.max_age_days:
            fail(f"catalog is stale: updated_at {updated_at} is "
                 f"{age_days:.1f} days old (max {args.max_age_days})")
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        fail("providers must be a non-empty list")

    seen_ids: set[str] = set()
    for p in providers:
        pid = p.get("id")
        if not pid:
            fail(f"provider missing id: {p!r}")
        if pid in seen_ids:
            fail(f"duplicate provider id: {pid}")
        seen_ids.add(pid)
        if p.get("provider_type") not in ("openai", "anthropic"):
            fail(f"{pid}: invalid provider_type {p.get('provider_type')!r}")
        models = p.get("models")
        if not isinstance(models, list) or not models:
            fail(f"{pid}: models must be a non-empty list")

        seen_names: set[str] = set()
        for m in models:
            name = m.get("name")
            if not name or not isinstance(name, str):
                fail(f"{pid}: model missing name: {m!r}")
            if name in seen_names:
                fail(f"{pid}: duplicate model name: {name}")
            seen_names.add(name)
            cw = m.get("context_window")
            if not isinstance(cw, int) or isinstance(cw, bool) or cw < 0:
                fail(f"{pid}/{name}: context_window must be a non-negative int, got {cw!r}")
            check_pricing(pid, name, m.get("pricing"))

        default = p.get("default_model")
        if not default:
            fail(f"{pid}: default_model must be set")
        if default not in seen_names:
            fail(f"{pid}: default_model {default!r} is not in models[]")
        if p.get("key_env"):
            default_model = next(m for m in models if m["name"] == default)
            if default_model.get("pricing") is None:
                fail(f"{pid}: default_model {default!r} has no pricing "
                     f"(only key-less local providers may omit it)")

    n_models = sum(len(p["models"]) for p in providers)
    print(f"OK: {len(providers)} providers, {n_models} models validated")


if __name__ == "__main__":
    main()
