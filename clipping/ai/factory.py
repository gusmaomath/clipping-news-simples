"""Seleciona o provedor de IA a partir da configuração salva (ai_config).
Sem chave válida, cai no provedor heurístico (offline)."""
from .. import db
from .heuristic import HeuristicProvider


def get_provider():
    cfg = db.get_ai_config()
    provider = (cfg.get("provider") or "anthropic").strip().lower()
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()
    base_url = (cfg.get("base_url") or "").strip() or None
    if api_key:
        try:
            if provider == "anthropic":
                from .anthropic_provider import AnthropicProvider
                return AnthropicProvider(model=model or "claude-opus-4-8", api_key=api_key, base_url=base_url)
            if provider == "openai":
                from .openai_provider import OpenAIProvider
                return OpenAIProvider(model=model or "gpt-4o-mini", api_key=api_key, base_url=base_url)
            if provider == "gemini":
                from .gemini_provider import GeminiProvider
                return GeminiProvider(model=model or "gemini-2.0-flash", api_key=api_key, base_url=base_url)
        except Exception:
            pass
    return HeuristicProvider()


def active_label():
    """Texto curto para a UI: qual motor está ativo."""
    p = get_provider()
    return f"{getattr(p, 'name', '?')} · {getattr(p, 'model', '?')}"
