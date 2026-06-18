"""Provedor OpenAI (GPT) via REST (httpx) — sem SDK extra.
Usa o endpoint chat/completions em modo JSON. Falha → heurística."""
import json
import httpx

from .base import Analysis
from .prompts import build_payload, JSON_HINT
from .heuristic import analyze as heuristic_analyze


class OpenAIProvider:
    name = "openai"

    def __init__(self, model="gpt-4o-mini", api_key=None, base_url=None):
        self.model = model
        self.api_key = api_key
        self.base = (base_url or "https://api.openai.com/v1").rstrip("/")

    def analyze(self, *, persona, lang, tags, title, text, published_at=None):
        try:
            system, user = build_payload(persona, lang, tags, title, text)
            body = {
                "model": self.model,
                "messages": [{"role": "system", "content": system + JSON_HINT},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 2000,
            }
            r = httpx.post(self.base + "/chat/completions",
                           headers={"Authorization": f"Bearer {self.api_key}",
                                    "Content-Type": "application/json"},
                           json=body, timeout=60)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            o = json.loads(content)
            return Analysis(bool(o.get("relevant", True)), o.get("score", 0),
                            o.get("sentiment", "Neutro"), o.get("title_t") or title,
                            o.get("summary_t") or "").clamped()
        except Exception:
            return heuristic_analyze(persona=persona, lang=lang, tags=tags,
                                     title=title, text=text, published_at=published_at)

    def ping(self):
        body = {"model": self.model, "max_tokens": 5,
                "messages": [{"role": "user", "content": "responda: ok"}]}
        r = httpx.post(self.base + "/chat/completions",
                       headers={"Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json"},
                       json=body, timeout=30)
        if r.status_code >= 400:
            try: msg = r.json().get("error", {}).get("message", "")
            except Exception: msg = r.text[:200]
            raise RuntimeError(f"HTTP {r.status_code}: {msg[:300]}")
        return "Conexão OK com a OpenAI."
