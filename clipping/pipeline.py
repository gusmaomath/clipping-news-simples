"""Worker de enriquecimento: extrai texto integral, agrupa 'mesmo evento'
(event_key) e analisa cada notícia por aba (relevância + score + sentimento +
tradução) usando o provedor de IA configurado. raw -> ready."""
import re

try:
    import trafilatura
except Exception:
    trafilatura = None
import httpx

from . import config, db
from .matching import matches_any_word
from .clustering import tokens, overlap
from .ai.factory import get_provider

_NL = re.compile(r"\n{3,}")
_TAGRE = re.compile(r"<[^>]+>")
_WSRE = re.compile(r"\s+")

def _kw(s):
    return [w.strip() for w in (s or "").split(",") if w.strip()]

def _belongs(a, tab, linked):
    if a["id"] in linked.get(tab["id"], set()):
        return True
    blob = (a.get("title") or "") + " " + (a.get("snippet") or "")
    bl, pref = _kw(tab.get("blacklist")), _kw(tab.get("preferences"))
    if bl and matches_any_word(blob, bl): return False
    if pref and not matches_any_word(blob, pref): return False
    return True

def _extract_full_text(url):
    """Baixa a página e devolve o corpo da matéria. Tenta trafilatura;
    se falhar, cai para uma extração crua dos <p>. Sempre busca o texto inteiro."""
    if not (url or "").startswith("http"):
        return None
    try:
        proxies = config.NEWS_PROXY or None
        with httpx.Client(timeout=config.REQUEST_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": config.USER_AGENT}, proxies=proxies) as cli:
            html = cli.get(url).text
    except Exception:
        return None
    if trafilatura:
        try:
            txt = trafilatura.extract(html, include_comments=False, include_tables=False,
                                      favor_recall=True)
            if txt and len(txt) > 200:
                return _NL.sub("\n\n", txt).strip()
        except Exception:
            pass
    # fallback cru: concatena o texto dos parágrafos <p>
    try:
        paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S | re.I)
        text = _WSRE.sub(" ", " ".join(_TAGRE.sub(" ", p) for p in paras)).strip()
        return text if len(text) > 200 else None
    except Exception:
        return None

def _assign_event_key(a, index, threshold=0.5):
    """Agrupa por 'mesmo evento': casa com uma notícia já indexada ou cria chave nova."""
    tk = tokens((a.get("title") or "") + " " + (a.get("snippet") or ""))
    best_key, best = None, 0.0
    for it in index:
        ov = overlap(tk, tokens((it.get("title") or "") + " " + (it.get("snippet") or "")))
        if ov > best:
            best, best_key = ov, it.get("event_key")
    if best_key and best >= threshold:
        return best_key
    return db.url_hash(a.get("url") or str(a["id"]))   # nova chave estável

def process_pending(limit=120):
    pend = db.list_pending(limit=limit)
    if not pend:
        return {"processed": 0, "analyzed": 0, "remaining": db.count_pending()}
    provider = get_provider()
    model = getattr(provider, "model", "?")
    tabs = db.list_tabs()
    links = db.article_tab_links()
    spam = db.spam_map()
    index = db.event_index()
    tagcache = {}  # tab_id -> ["nome: kw", ...]
    processed, analyzed = 0, 0
    for a in pend:
        db.set_status(a["id"], "processing")
        # 1) texto integral (sempre tenta puxar a matéria inteira)
        full = _extract_full_text(a.get("url"))
        if full:
            db.set_full_text(a["id"], full)
            db.set_content(a["id"], full)      # alimenta também o popup, sem re-baixar
            a["full_text"] = full
        text = a.get("full_text") or a.get("content") or a.get("snippet") or ""
        # 2) agrupamento (mesmo evento)
        key = _assign_event_key(a, index)
        db.set_event_key(a["id"], key)
        index.append({"title": a.get("title"), "snippet": a.get("snippet"), "event_key": key})
        # 3) análise por aba (relevância, score, sentimento, tradução)
        uhash = db.url_hash(a.get("url") or "")
        for t in tabs:
            if uhash in spam.get(t["id"], set()):      # respeita a lixeira da aba
                continue
            if not _belongs(a, t, links):
                continue
            if t["id"] not in tagcache:
                tagcache[t["id"]] = [f'{g["name"]}: {g["keywords"]}' for g in db.list_tags(tab_id=t["id"])]
            an = provider.analyze(persona=t.get("persona") or "", lang=t.get("lang") or "pt-BR",
                                  tags=tagcache[t["id"]], title=a.get("title") or "", text=text,
                                  published_at=a.get("published_at"))
            db.upsert_ai(a["id"], t["id"], an.relevant, an.score, an.sentiment,
                         an.title_t, an.summary_t, model)
            analyzed += 1
        db.set_status(a["id"], "ready")
        processed += 1
    return {"processed": processed, "analyzed": analyzed, "remaining": db.count_pending(),
            "engine": getattr(provider, "name", "?"), "model": model}
