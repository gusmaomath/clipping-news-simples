"""Provedor de fallback (sem chave de API): análise por heurística, 100% offline.
Mantém o sistema (score, sentimento, relevância, Portal) funcionando sem IA externa."""
from datetime import datetime, timezone
from ..matching import norm, matches_any_word

POS = ["alta", "lucro", "aprova", "crescimento", "recorde", "sobe", "avanco", "acordo",
       "expansao", "dividendo", "valoriza", "ganho", "supera", "otimista"]
NEG = ["queda", "prejuizo", "cai", "perda", "multa", "demiss", "crise", "fraude", "rombo",
       "despenca", "recua", "calote", "inadimpl"]
RISCO = ["risco", "alerta", "ameaca", "investiga", "processo", "vazamento", "ataque", "golpe", "fraude"]
OPORT = ["oportunidade", "chance", "lancamento", "parceria", "novo fundo", "ipo", "incentivo", "abertura"]

def _recency_bonus(iso):
    if not iso: return 0.0
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        h = (datetime.now(timezone.utc) - d).total_seconds() / 3600
        return max(0.0, 30.0 - h / 4.0)      # até +30 para notícias muito recentes
    except Exception:
        return 0.0

def _count(text, words):
    return sum(1 for w in words if w in text)

def analyze(*, persona, lang, tags, title, text, published_at=None):
    from .base import Analysis
    blob = norm((title or "") + " " + (text or ""))
    pos, neg, risco, oport = _count(blob, POS), _count(blob, NEG), _count(blob, RISCO), _count(blob, OPORT)
    if oport and oport >= neg: sentiment = "Oportunidade"
    elif risco and risco >= pos: sentiment = "Risco"
    elif pos > neg: sentiment = "Positivo"
    elif neg > pos: sentiment = "Negativo"
    else: sentiment = "Neutro"
    # offline não faz juízo semântico de relevância (a aba já filtrou por palavras-chave)
    tag_words = [w for t in (tags or []) for w in t.split(",") if w.strip()]
    relevant = True
    # score: base + recência + casamento de tags + tamanho do texto
    score = 45.0 + _recency_bonus(published_at)
    if tag_words and matches_any_word(blob, tag_words): score += 15
    score += min(10.0, len(text or "") / 400.0)
    if sentiment in ("Oportunidade", "Risco"): score += 8
    return Analysis(relevant, score, sentiment,
                    (title or "").strip(), _summary(text)).clamped()

def _summary(text, max_chars=1200):
    """Resumo offline: primeiras frases até ~max_chars (sem cortar no meio da frase)."""
    t = " ".join((text or "").split())
    if len(t) <= max_chars:
        return t
    import re as _re
    out = ""
    for sent in _re.split(r"(?<=[.!?])\s+", t):
        if len(out) + len(sent) + 1 > max_chars:
            break
        out += (" " if out else "") + sent
    return (out or t[:max_chars]).strip()

class HeuristicProvider:
    name = "heuristic"
    model = "heuristic"
    def analyze(self, *, persona, lang, tags, title, text, published_at=None):
        return analyze(persona=persona, lang=lang, tags=tags, title=title,
                       text=text, published_at=published_at)
    def ping(self):
        return "Modo heurístico (offline) ativo — sem IA externa, sem chave."
