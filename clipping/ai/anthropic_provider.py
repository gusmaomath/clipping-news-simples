"""Provedor Claude (Anthropic). Uma chamada por (notícia, aba) devolve
relevância + score + sentimento + tradução via saída estruturada.
O bloco da PERSONA usa prompt caching (barato a partir do 2º artigo da mesma aba)."""
from typing import Literal
from pydantic import BaseModel

from .base import Analysis, SENTIMENTS
from .prompts import INSTRUCOES
from .heuristic import analyze as heuristic_analyze


class _Out(BaseModel):
    relevant: bool
    score: float
    sentiment: Literal["Positivo", "Neutro", "Negativo", "Risco", "Oportunidade"]
    title_t: str
    summary_t: str


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model="claude-opus-4-8", api_key=None, base_url=None):
        import anthropic
        self.model = model
        kw = {}
        if api_key: kw["api_key"] = api_key
        if base_url: kw["base_url"] = base_url
        self.client = anthropic.Anthropic(**kw)

    def analyze(self, *, persona, lang, tags, title, text, published_at=None):
        system = [{
            "type": "text",
            "text": (INSTRUCOES + "\n\nIDIOMA_SAIDA: " + (lang or "pt-BR")
                     + "\nTAGS: " + ", ".join(tags or [])
                     + "\n\nPERSONA:\n" + (persona or "(sem persona definida — use bom senso jornalístico)")),
            "cache_control": {"type": "ephemeral"},
        }]
        user = f"TÍTULO: {title}\n\nTEXTO:\n{(text or '')[:16000]}"
        try:
            r = self.client.messages.parse(
                model=self.model, max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=_Out,
            )
            o = r.parsed_output
            return Analysis(o.relevant, o.score, o.sentiment, o.title_t, o.summary_t).clamped()
        except Exception:
            # falha de rede/quota/etc: degrada para heurística em vez de derrubar o lote
            return heuristic_analyze(persona=persona, lang=lang, tags=tags,
                                     title=title, text=text, published_at=published_at)

    def ping(self):
        self.client.messages.create(model=self.model, max_tokens=5,
                                     messages=[{"role": "user", "content": "responda: ok"}])
        return "Conexão OK com o Claude."
