import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID: str = os.environ["TELEGRAM_CHAT_ID"]
KOBIS_API_KEY: str = os.environ.get("KOFIC_API_KEY", "")
WATCHA_EMAIL: str = os.environ.get("WATCHA_EMAIL", "")
WATCHA_PASSWORD: str = os.environ.get("WATCHA_PASSWORD", "")

# Cinema chain login credentials (optional — for booking history)
CGV_ID: str = os.environ.get("CGV_ID", "")
CGV_PASSWORD: str = os.environ.get("CGV_PASSWORD", "")
LOTTE_ID: str = os.environ.get("LOTTECINEMA_ID", "")
LOTTE_PASSWORD: str = os.environ.get("LOTTECINEMA_PASSWORD", "")
MEGABOX_ID: str = os.environ.get("MEGABOX_ID", "")
MEGABOX_PASSWORD: str = os.environ.get("MEGABOX_PASSWORD", "")

# LLM (at least one provider required for NLP intent classification)
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "")  # openai | anthropic | google
LLM_MODEL: str = os.environ.get("LLM_MODEL", "")  # empty = provider default
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")

# Per-provider API keys (any one is enough for NLP)
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

# Map provider name → env var value
_PROVIDER_KEYS: dict[str, str] = {
    "openai": OPENAI_API_KEY,
    "anthropic": ANTHROPIC_API_KEY,
    "google": GEMINI_API_KEY,
}


def resolve_llm() -> tuple[str, str, str]:
    """Resolve the best available LLM provider, API key, and model.

    Priority:
    1. LLM_API_KEY + LLM_PROVIDER env vars (explicit single-provider config)
    2. Per-provider env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY)
    3. Dashboard settings (DigestSettings JSON)

    Returns (provider, api_key, model). All empty strings if nothing configured.
    """
    from cinepyle.digest.settings import DigestSettings

    settings = DigestSettings.load()
    model = LLM_MODEL or settings.llm_model

    # 1) Explicit LLM_API_KEY
    if LLM_API_KEY:
        provider = LLM_PROVIDER or settings.llm_provider or "openai"
        return provider, LLM_API_KEY, model

    # 2) Per-provider env vars — prefer LLM_PROVIDER if set, else first available
    if LLM_PROVIDER and _PROVIDER_KEYS.get(LLM_PROVIDER):
        return LLM_PROVIDER, _PROVIDER_KEYS[LLM_PROVIDER], model

    for prov, key in _PROVIDER_KEYS.items():
        if key:
            return prov, key, model

    # 3) Dashboard settings
    for prov in settings.llm_provider_order:
        key = settings.active_llm_api_key(prov)
        if key:
            return prov, key, settings.llm_models.get(prov, "") or model

    return "", "", model


# Dashboard (optional)
DASHBOARD_PORT: int = int(os.environ.get("DASHBOARD_PORT", "3847"))
