# recursive-providers

LLM provider preset catalog for [Recursive](https://github.com/jeffkit/Recursive) — model names, API endpoints, context windows, and pricing.

## What this is

`providers.json` is the single source of truth for provider configuration used by Recursive. It is fetched automatically by the agent at startup (when the local cache is older than 7 days) and can be updated manually:

```bash
recursive providers update
```

## Schema

```json
{
  "schema_version": 1,
  "updated_at": "2026-06-06T00:00:00Z",
  "source_url": "https://raw.githubusercontent.com/jeffkit/recursive-providers/main/providers.json",
  "providers": [
    {
      "id": "anthropic",
      "name": "Anthropic",
      "provider_type": "anthropic",
      "api_base": "https://api.anthropic.com",
      "anthropic_api_base": null,
      "default_model": "claude-sonnet-4-6",
      "models": [
        {
          "name": "claude-sonnet-4-6",
          "context_window": 1000000,
          "pricing": {
            "input_per_million": 3.00,
            "output_per_million": 15.00,
            "cache_hit_input_per_million": 0.30
          }
        }
      ],
      "mainland_accessible": false,
      "key_env": "ANTHROPIC_API_KEY",
      "key_url": "https://console.anthropic.com/settings/keys"
    }
  ]
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | int | Must be `1` |
| `updated_at` | string | RFC 3339 timestamp |
| `source_url` | string | Canonical URL of this file |
| `providers[].id` | string | Unique identifier (used in `~/.recursive/config.toml` as `preset`) |
| `providers[].provider_type` | string | `"openai"` or `"anthropic"` |
| `providers[].api_base` | string | OpenAI-compatible endpoint |
| `providers[].anthropic_api_base` | string\|null | Anthropic Messages API endpoint, if the provider supports both protocols |
| `providers[].default_model` | string | Recommended model for new users |
| `models[].context_window` | int | Max input tokens |
| `models[].pricing` | object\|null | USD per million tokens; `null` for free/local models |
| `models[].pricing.cache_hit_input_per_million` | float\|null | Discounted rate for cache-hit input tokens |
| `providers[].mainland_accessible` | bool | Accessible from mainland China without VPN |
| `providers[].key_env` | string | Environment variable name for the API key |

## Covered providers (12)

Pricing data for 11 providers is auto-synced weekly from
[LiteLLM's model_prices_and_context_window.json](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json).
Ollama is kept manually (free/local, no pricing).

| ID | Name | Mainland | Sync |
|---|---|---|---|
| `anthropic` | Anthropic | ✗ | LiteLLM |
| `openai` | OpenAI | ✗ | LiteLLM |
| `deepseek` | DeepSeek | ✓ | LiteLLM |
| `minimax` | MiniMax | ✓ | LiteLLM |
| `zhipu` | 智谱 AI (GLM) | ✓ | LiteLLM |
| `moonshot` | 月之暗面 (Kimi) | ✓ | LiteLLM |
| `dashscope` | 阿里云通义千问 | ✓ | LiteLLM |
| `gemini` | Google Gemini | ✗ | LiteLLM |
| `groq` | Groq | ✗ | LiteLLM |
| `mistral` | Mistral AI | ✗ | LiteLLM |
| `xai` | xAI (Grok) | ✗ | LiteLLM |
| `ollama` | Ollama (本地) | ✓ | Manual |

> Doubao, Hunyuan, and StepFun are not yet covered by LiteLLM and will be
> added once upstream support lands.

## Contributing

Pricing changes fast. PRs to update model names, pricing, or add new providers are welcome.

1. Edit `providers.json`
2. Update `updated_at` to today's date
3. Open a PR with a brief note on what changed and a source link

## License

CC0 — public domain.
