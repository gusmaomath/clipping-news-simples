"""Provedor Google Gemini via REST (httpx) — sem SDK extra.
Usa generateContent em modo JSON. Falha → heurística."""
import json
import httpx

from .base import Analysis
from .prompts import build_payload, JSON_HINT
from .heuristic import analyze as heuristic_analyze


class GeminiProvider:
    name = "gemini"

    def __init__(self, model="gemini-2.0-flash", api_key=None, base_url=None):
        self.model = model
        self.api_key = api_key
        self.base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

    def analyze(self, *, persona, lang, tags, title, text, published_at=None):
        try:
            system, user = build_payload(persona, lang, tags, title, text)
            body = {
                "contents": [{"parts": [{"text": system + "\n\n" + user + JSON_HINT}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                                     "maxOutputTokens": 2000},
            }
            url = f"{self.base}/models/{self.model}:generateContent?key={self.api_key}"
            r = httpx.post(url, json=body, timeout=60)
            r.raise_for_status()
            content = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            o = json.loads(content)
            return Analysis(bool(o.get("relevant", True)), o.get("score", 0),
                            o.get("sentiment", "Neutro"), o.get("title_t") or title,
                            o.get("summary_t") or "").clamped()
        except Exception:
            return heuristic_analyze(persona=persona, lang=lang, tags=tags,
                                     title=title, text=text, published_at=published_at)

    def ping(self):
        url = f"{self.base}/models/{self.model}:generateContent?key={self.api_key}"
        r = httpx.post(url, json={"contents": [{"parts": [{"text": "responda: ok"}]}]}, timeout=30)
        if r.status_code >= 400:
            try: msg = r.json().get("error", {}).get("message", "")
            except Exception: msg = r.text[:200]
            raise RuntimeError(f"HTTP {r.status_code}: {msg[:300]}")
        return "Conexão OK com o Gemini."
