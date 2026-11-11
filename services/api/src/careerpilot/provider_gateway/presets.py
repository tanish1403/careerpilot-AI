"""Provider presets. Base URLs are SUGGESTIONS only; users edit them (Setting 'provider_presets')."""
NOTE = ("Suggested defaults only. Verify compatibility and the base URL with your provider; "
        "model names, capabilities and pricing are not assumed.")


def _p(id_, name, protocol, url, key=True, local=False, extra_note=""):
    return {"id": id_, "name": name, "protocol": protocol, "base_url": url, "requires_key": key,
            "local": local, "note": (extra_note + " " + NOTE).strip()}


DEFAULT_PRESETS: list[dict] = [
    _p("omniroute", "OmniRoute", "openai_compatible", "http://localhost:20128/v1", False, True,
       "Self-hosted router; port may differ."),
    _p("openrouter", "OpenRouter", "openai_compatible", "https://openrouter.ai/api/v1"),
    _p("freellmapi", "FreeLLMAPI", "openai_compatible", "http://localhost:3001/v1", False, True,
       "Self-hosted gateway; port may differ."),
    _p("ollama", "Ollama", "ollama", "http://localhost:11434", False, True),
    _p("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com"),
    _p("openai", "OpenAI", "openai_compatible", "https://api.openai.com/v1"),
    _p("gemini", "Gemini (OpenAI-compatible endpoint)", "openai_compatible",
       "https://generativelanguage.googleapis.com/v1beta/openai"),
    _p("groq", "Groq", "openai_compatible", "https://api.groq.com/openai/v1"),
    _p("together", "Together", "openai_compatible", "https://api.together.xyz/v1"),
    _p("deepseek", "DeepSeek", "openai_compatible", "https://api.deepseek.com/v1"),
    _p("mistral", "Mistral", "openai_compatible", "https://api.mistral.ai/v1"),
    _p("lmstudio", "LM Studio", "openai_compatible", "http://localhost:1234/v1", False, True),
    _p("vllm", "vLLM", "openai_compatible", "http://localhost:8000/v1", False, True),
    _p("custom", "Custom (OpenAI-compatible)", "openai_compatible", "", False, False),
]
