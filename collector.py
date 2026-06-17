"""Scraper: puxa RSS/Google News com proxy opcional, só da semana atual,
guarda a DATA ORIGINAL, aplica blacklist das abas ANTES de salvar e
deduplica por hash de URL. Volume até MAX_PER_SOURCE por fonte."""
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import feedparser
import httpx

import config
import db
from matching import matches_any_word

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

def clean(t):
    if not t: return ""
    t = _TAG.sub(" ", t).replace("&nbsp;", " ").replace("&amp;", "&")
    return _WS.sub(" ", t).strip()

def _client():
    kw = dict(timeout=config.REQUEST_TIMEOUT, headers={"User-Agent": config.USER_AGENT},
              follow_redirects=True)
    if config.NEWS_PROXY:
        kw["proxies"] = config.NEWS_PROXY          # <-- injeta o proxy aqui
    return httpx.Client(**kw)

def google_news_url(term):
    q = urllib.parse.quote(term)
    return (f"https://news.google.com/rss/search?q={q}"
            f"&hl={config.HL}&gl={config.GL}&ceid={config.CEID}")

def _published(e):
    """Data ORIGINAL de publicação (não a hora da coleta)."""
    for k in ("published_parsed", "updated_parsed"):
        v = e.get(k)
        if v:
            try: return datetime.fromtimestamp(time.mktime(v), tz=timezone.utc)
            except Exception: pass
    return None

def _image(e):
    m = e.get("media_content") or e.get("media_thumbnail")
    if m and isinstance(m, list) and m[0].get("url"): return m[0]["url"]
    for enc in e.get("links", []):
        if enc.get("type", "").startswith("image"): return enc.get("href")
    return None

def _start_of_week():
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

def _fetch_feed(url, client):
    """Baixa o feed (com proxy) e devolve as entradas parseadas."""
    try:
        r = client.get(url)
        return feedparser.parse(r.content).entries
    except Exception:
        return feedparser.parse(url).entries  # fallback sem proxy

def _entries(src, client, week_start):
    url = src["value"] if src["type"] == "rss" else google_news_url(src["value"])
    out = []
    for e in _fetch_feed(url, client)[:config.MAX_PER_SOURCE]:
        link, title = e.get("link"), e.get("title")
        if not link or not title:
            continue
        pub = _published(e)
        if pub is None or pub < week_start:      # recência estrita: só a semana atual
            continue
        out.append({"title": clean(title), "url": link, "source_id": src["id"],
                    "source_name": src["name"], "snippet": clean(e.get("summary") or e.get("description") or "")[:300],
                    "published_at": pub.isoformat(), "image_url": _image(e)})
    return out

# ===========================================================================
# STUBS DE IA (futuro) — onde plugar a inteligência ANTES de salvar no banco.
# def _ai_ler_texto_completo(url: str) -> str:
#     """Baixa a página e extrai o corpo inteiro do artigo (ex.: trafilatura)."""
#     ...
# def _ai_resumir(texto: str) -> str:
#     """Gera um resumo curto do artigo (ex.: Ollama/OpenAI)."""
#     ...
# def _ai_filtro_semantico(item: dict, contexto_da_aba: dict) -> bool:
#     """Decide, por SIGNIFICADO (não só palavra), se a notícia interessa.
#        Retornar False aqui faria a notícia NÃO ser salva."""
#     ...
# Fluxo futuro dentro de collect_all(), por item, antes do insert:
#     texto = _ai_ler_texto_completo(it["url"])
#     if not _ai_filtro_semantico(it, contexto):  # filtragem inteligente
#         continue
#     it["snippet"] = _ai_resumir(texto)          # resumo gerado por IA
# ===========================================================================

def collect_all():
    sources = db.list_sources(active_only=True)
    # blacklist PRÉ-BANCO: união das blacklists de todas as abas
    bl = []
    for t in db.list_tabs():
        bl += [w.strip() for w in (t.get("blacklist") or "").split(",") if w.strip()]
    week_start = _start_of_week()

    items = []
    with _client() as client:
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            futs = {pool.submit(_entries, s, client, week_start): s for s in sources}
            for fut in as_completed(futs):
                try: items.extend(fut.result())
                except Exception: pass

    added, blocked, dup = 0, 0, 0
    seen = set()
    for it in items:
        h = db.url_hash(it["url"])
        if h in seen:               # dedup dentro da própria rodada
            continue
        seen.add(h)
        # barreira de filtros antes do banco
        if bl and matches_any_word(it["title"] + " " + it["snippet"], bl):
            blocked += 1
            continue
        if db.exists_hash(h):       # trava definitiva: já existe -> nunca duplica
            dup += 1
            continue
        # (futuro) aqui entraria _ai_filtro_semantico / _ai_resumir antes de salvar
        if db.insert_article(it):
            added += 1
    return {"checked": len(seen), "added": added, "blocked": blocked, "duplicates": dup,
            "week_start": week_start.isoformat()}
