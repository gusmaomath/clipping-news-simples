"""API do Clipping News (abas, tags, filtros de tempo, agrupamento, busca, resumo)."""
import re
import pathlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

try:
    import trafilatura
except Exception:
    trafilatura = None
import httpx

from . import config, db, collector, clustering, pipeline
from .ai import factory as ai_factory
from .matching import matches_any_word, matches_any_sub

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"
scheduler = BackgroundScheduler()
_NL = re.compile(r"\n{3,}")

def _auto():
    try:
        r = collector.collect_all(); print(f"[coleta] +{r['added']} | bloqueadas {r['blocked']} | dup {r['duplicates']}")
    except Exception as e:
        print("[coleta] erro:", e)
    try:
        p = pipeline.process_pending(); print(f"[ia] {p['processed']} processadas | motor {p.get('engine')}")
    except Exception as e:
        print("[ia] erro:", e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.add_job(_auto, "interval", minutes=config.COLLECT_INTERVAL_MIN, id="c", replace_existing=True)
    scheduler.start()
    print(f"Clipping News em http://localhost:8000 | coleta a cada {config.COLLECT_INTERVAL_MIN} min"
          + (" | proxy ON" if config.NEWS_PROXY else ""))
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title="Clipping News", lifespan=lifespan)

# ---------- modelos ----------
class SourceIn(BaseModel):
    name: str; type: str; value: str
class ToggleIn(BaseModel):
    active: bool
class TabIn(BaseModel):
    name: str; preferences: str = ""; blacklist: str = ""; persona: str = ""; lang: str = "pt-BR"
class AiConfigIn(BaseModel):
    provider: str = "anthropic"; model: str = "claude-opus-4-8"; api_key: str = ""; base_url: str = ""
class SpamIn(BaseModel):
    ids: list[int] = []
class TabExport(BaseModel):
    name: str; preferences: str = ""; blacklist: str = ""; persona: str = ""; lang: str = "pt-BR"
    tags: list[dict] = []; searches: list[str] = []
class TagIn(BaseModel):
    tab_id: int; name: str; keywords: str = ""
class TagEditIn(BaseModel):
    name: str; keywords: str = ""
class SearchIn(BaseModel):
    term: str
class IdsIn(BaseModel):
    ids: list[int] = []

def _kw(s): return [w.strip() for w in (s or "").split(",") if w.strip()]

# ---------- fontes ----------
@app.get("/api/sources")
def get_sources(): return db.list_sources()
@app.post("/api/sources")
def post_source(s: SourceIn):
    if s.type not in ("rss", "google_news"): raise HTTPException(400, "tipo inválido")
    if not s.name.strip() or not s.value.strip(): raise HTTPException(400, "obrigatório")
    if db.source_exists(s.value): raise HTTPException(409, "Essa fonte já existe (mesmo link).")
    return {"id": db.add_source(s.name, s.type, s.value)}
@app.delete("/api/sources/{sid}")
def del_source(sid: int): db.delete_source(sid); return {"ok": True}
@app.patch("/api/sources/{sid}")
def patch_source(sid: int, t: ToggleIn): db.toggle_source(sid, t.active); return {"ok": True}

# ---------- abas ----------
@app.get("/api/tabs")
def get_tabs(): return db.list_tabs()
@app.post("/api/tabs")
def post_tab(t: TabIn):
    if not t.name.strip(): raise HTTPException(400, "nome obrigatório")
    return {"id": db.add_tab(t.name, t.preferences, t.blacklist)}
@app.put("/api/tabs/{tid}")
def put_tab(tid: int, t: TabIn):
    db.update_tab(tid, t.name, t.preferences, t.blacklist, t.persona, t.lang); return {"ok": True}
@app.post("/api/tabs/{tid}/move/{d}")
def move_tab(tid: int, d: int): db.move_tab(tid, 1 if d > 0 else -1); return {"ok": True}
@app.delete("/api/tabs/{tid}")
def del_tab(tid: int, purge: int = 0):
    removed = _purge_exclusive_articles(tid) if purge else 0
    db.delete_tab(tid)
    return {"ok": True, "removed_articles": removed}

# ---------- exportar / importar configuração de uma seção (aba) ----------
@app.get("/api/tabs/{tid}/export")
def export_tab(tid: int):
    t = db.get_tab(tid)
    if not t: raise HTTPException(404, "aba não encontrada")
    return {"name": t["name"], "preferences": t.get("preferences", ""), "blacklist": t.get("blacklist", ""),
            "persona": t.get("persona", ""), "lang": t.get("lang", "pt-BR"),
            "tags": [{"name": g["name"], "keywords": g["keywords"]} for g in db.list_tags(tab_id=tid)],
            "searches": [s["term"] for s in db.list_searches(tid)]}

@app.post("/api/tabs/import")
def import_tab(t: TabExport):
    name = (t.name or "Aba importada").strip() or "Aba importada"
    tid = db.add_tab(name, t.preferences, t.blacklist)
    db.update_tab(tid, name, t.preferences, t.blacklist, t.persona, t.lang)
    for g in t.tags:
        if isinstance(g, dict) and (g.get("name") or "").strip():
            db.add_tag(tid, g["name"], g.get("keywords", ""))
    for term in t.searches:
        if term and str(term).strip(): db.add_search(tid, str(term).strip())
    return {"id": tid, "name": name}

# ---------- tags por aba ----------
@app.get("/api/tags")
def get_tags(tab_id: int = None): return db.list_tags(tab_id=tab_id)
@app.post("/api/tags")
def post_tag(t: TagIn):
    if not t.name.strip(): raise HTTPException(400, "nome obrigatório")
    return {"id": db.add_tag(t.tab_id, t.name, t.keywords)}
@app.put("/api/tags/{tid}")
def put_tag(tid: int, t: TagEditIn): db.update_tag(tid, t.name, t.keywords); return {"ok": True}
@app.delete("/api/tags/{tid}")
def del_tag(tid: int): db.delete_tag(tid); return {"ok": True}

# ---------- buscas Google News por aba ----------
@app.get("/api/tabs/{tid}/searches")
def get_searches(tid: int): return db.list_searches(tid)
@app.post("/api/tabs/{tid}/searches")
def post_search(tid: int, s: SearchIn):
    if not s.term.strip(): raise HTTPException(400, "termo obrigatório")
    return {"id": db.add_search(tid, s.term)}
@app.delete("/api/searches/{sid}")
def del_search(sid: int): db.delete_search(sid); return {"ok": True}

# ---------- helpers de filtro ----------
def _tab_pass(a, tab):
    blob = (a.get("title") or "") + " " + (a.get("snippet") or "")
    bl = _kw(tab.get("blacklist"))
    pref = _kw(tab.get("preferences"))
    if bl and matches_any_word(blob, bl): return False
    if pref and not matches_any_word(blob, pref): return False
    return True

def _belongs(a, tab, links):
    """A notícia pertence à aba se passa no filtro OU foi trazida por uma busca da aba."""
    return _tab_pass(a, tab) or a["id"] in links.get(tab["id"], set())

def _purge_exclusive_articles(tid):
    """Apaga notícias que pertencem SÓ a esta aba (em nenhuma outra restante)."""
    tabs = db.list_tabs()
    target = next((t for t in tabs if t["id"] == tid), None)
    if not target:
        return 0
    others = [t for t in tabs if t["id"] != tid]
    links = db.article_tab_links()
    ids = [a["id"] for a in db.list_articles(limit=10**9)
           if _belongs(a, target, links) and not any(_belongs(a, o, links) for o in others)]
    return db.delete_articles(ids)

def _parse_dt(s):
    if not s: return None
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _time_ok(a, since_hours, date_s, from_s, to_s):
    if not (since_hours or date_s or from_s or to_s): return True
    pub = _parse_dt(a.get("published_at"))
    if not pub: return False
    now = datetime.now(timezone.utc)
    if since_hours and pub < now - timedelta(hours=since_hours): return False
    if date_s and pub.date().isoformat() != date_s: return False
    fd, td = _parse_dt(from_s), _parse_dt(to_s)
    if fd and pub < fd: return False
    if td and pub > td: return False
    return True

def _article_tags(a, tagdefs):
    blob = (a.get("title") or "") + " " + (a.get("snippet") or "") + " " + (a.get("content") or "")
    return [t["name"] for t in tagdefs if matches_any_sub(blob, _kw(t["keywords"]))]

def _resolve_ai(a, cand_tabs, aim):
    """Escolhe a análise de IA (maior score) entre as abas candidatas. Devolve (visível, ai)."""
    ais = [aim[(a["id"], t["id"])] for t in cand_tabs if (a["id"], t["id"]) in aim]
    if not ais:
        return True, None                       # sem IA ainda → mostra com valores neutros
    rel = [x for x in ais if x["relevant"]]
    chosen = max(rel or ais, key=lambda x: x["score"])
    return bool(rel), chosen

def _attach_ai(a, ai):
    a["score"] = round(ai["score"], 1) if ai else 0
    a["sentiment"] = ai["sentiment"] if ai else "Neutro"
    a["title_disp"] = (ai.get("title_t") if ai and ai.get("title_t") else a.get("title"))
    a["snippet_disp"] = (ai.get("summary_t") if ai and ai.get("summary_t") else a.get("snippet"))

def _make_cluster(members):
    members = sorted(members, key=lambda m: (m.get("published_at") or m.get("fetched_at") or ""), reverse=True)
    lead = members[0]
    sources = sorted({m.get("source_name") for m in members if m.get("source_name")})
    score = max((m.get("score", 0) for m in members), default=0)
    return {"lead": lead, "others": members[1:], "size": len(members), "sources": sources,
            "newest": lead.get("published_at") or lead.get("fetched_at") or "", "score": score}

def _group(sel):
    keyed, unkeyed = {}, []
    for a in sel:
        k = a.get("event_key")
        (keyed.setdefault(k, []).append(a) if k else unkeyed.append(a))
    clusters = [_make_cluster(m) for m in keyed.values()]
    for c in clustering.cluster(unkeyed):       # itens sem event_key: método antigo
        c["score"] = max([c["lead"].get("score", 0)] + [o.get("score", 0) for o in c["others"]], default=0)
        clusters.append(c)
    return clusters

def _build_feed(tab, q, since_hours, date_s, from_s, to_s, tag_filter, group=True, sort="recent"):
    tabs = db.list_tabs()
    if not tabs:
        return {"no_tabs": True, "clusters": [], "available_tags": []}
    tabs_by_id = {t["id"]: t for t in tabs}
    arts = db.list_articles(limit=3000)
    links = db.article_tab_links()
    aim = db.ai_map()
    spam = db.spam_map()
    specific = tab.strip().isdigit() and int(tab) in tabs_by_id
    if specific:
        t = tabs_by_id[int(tab)]
        cand = [t]
        tagdefs = db.list_tags(tab_id=t["id"])
    else:
        cand = None  # por artigo: as abas a que ele pertence
        tagdefs = db.list_tags()
    ql = q.strip().lower()
    sel = []
    for a in arts:
        # escopo / pertencimento
        ctabs = cand if specific else [tt for tt in tabs if _belongs(a, tt, links)]
        if not ctabs:
            continue
        uhash = db.url_hash(a.get("url") or "")
        # spam: oculta se descartada em TODAS as abas candidatas
        if ctabs and all(uhash in spam.get(tt["id"], set()) for tt in ctabs):
            continue
        if not _time_ok(a, since_hours, date_s, from_s, to_s): continue
        if ql and ql not in ((a.get("title") or "") + " " + (a.get("snippet") or "")).lower(): continue
        visible, ai = _resolve_ai(a, ctabs, aim)
        if not visible:                          # IA julgou irrelevante p/ a(s) aba(s)
            continue
        _attach_ai(a, ai)
        a["tags"] = _article_tags(a, tagdefs)
        if tag_filter and not (set(tag_filter) & set(a["tags"])): continue
        sel.append(a)
    available = sorted({t["name"] for t in tagdefs})
    if group:
        clusters = _group(sel)
    else:
        clusters = [{"lead": a, "others": [], "size": 1, "sources": [a.get("source_name")],
                     "newest": a.get("published_at"), "score": a.get("score", 0)} for a in sel]
    if sort == "score":
        clusters.sort(key=lambda c: c.get("score", 0), reverse=True)
    else:
        clusters.sort(key=lambda c: c.get("newest") or "", reverse=True)
    return {"no_tabs": False, "clusters": clusters, "available_tags": available}

# ---------- feed ----------
@app.post("/api/articles/delete")
def delete_articles_ep(b: IdsIn):
    return {"ok": True, "removed": db.delete_articles(b.ids)}

@app.get("/api/articles")
def get_articles(tab: str = "", q: str = "", since_hours: float = 0, date: str = "",
                 dt_from: str = "", dt_to: str = "", tags: str = "", group: int = 1, sort: str = "recent",
                 page: int = 1, per_page: int = 15):
    tag_filter = _kw(tags)
    res = _build_feed(tab, q, since_hours, date, dt_from, dt_to, tag_filter, group=bool(group), sort=sort)
    total = len(res["clusters"])
    per_page = max(1, per_page)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    res["clusters"] = res["clusters"][start:start + per_page]
    res["count"] = total
    res["page"] = page; res["per_page"] = per_page; res["pages"] = pages; res["total"] = total
    res["pending"] = db.count_pending()
    return res

# ---------- busca global (todas as notícias salvas) ----------
@app.get("/api/search")
def search(q: str = ""):
    ql = q.strip().lower()
    if not ql: return {"results": []}
    out = []
    for a in db.list_articles(limit=5000):
        blob = ((a.get("title") or "") + " " + (a.get("snippet") or "")).lower()
        if ql in blob:
            out.append({"id": a["id"], "title": a["title"], "source_name": a["source_name"],
                        "published_at": a["published_at"], "snippet": a["snippet"], "url": a["url"]})
        if len(out) >= 60: break
    return {"results": out}

# ---------- artigo completo (popup) ----------
@app.get("/api/article/{aid}")
def get_article(aid: int):
    a = db.get_article(aid)
    if not a: raise HTTPException(404, "não encontrado")
    if not a.get("content") and trafilatura and (a["url"] or "").startswith("http"):
        try:
            proxies = config.NEWS_PROXY or None
            with httpx.Client(timeout=config.REQUEST_TIMEOUT, follow_redirects=True,
                              headers={"User-Agent": config.USER_AGENT}, proxies=proxies) as cli:
                html = cli.get(a["url"]).text
            txt = trafilatura.extract(html, include_comments=False, include_tables=False)
            if txt:
                txt = _NL.sub("\n\n", txt).strip()
                db.set_content(aid, txt); a["content"] = txt
        except Exception:
            pass
    return a

# ---------- RESUMO EXECUTIVO (payload pronto para IA) ----------
@app.get("/api/resumo-executivo")
def resumo_executivo(tab: str = "", q: str = "", since_hours: float = 0, date: str = "",
                     dt_from: str = "", dt_to: str = "", tags: str = ""):
    res = _build_feed(tab, q, since_hours, date, dt_from, dt_to, _kw(tags), group=True)
    if res.get("no_tabs"):
        raise HTTPException(400, "crie uma aba primeiro")
    tabs = {t["id"]: t for t in db.list_tabs()}
    nome = tabs[int(tab)]["name"] if tab.strip().isdigit() and int(tab) in tabs else "Todas"
    noticias = []
    for c in res["clusters"]:
        a = c["lead"]
        noticias.append({
            "titulo": a.get("title"), "fonte": a.get("source_name"),
            "publicado_em": a.get("published_at"), "url": a.get("url"),
            "trecho": a.get("snippet"), "tags": a.get("tags", []),
            "outras_fontes": c["size"] - 1, "fontes": c["sources"],
        })
    payload = {
        "aba": nome, "gerado_em": datetime.now(timezone.utc).isoformat(),
        "filtros": {"q": q, "since_hours": since_hours, "date": date,
                    "dt_from": dt_from, "dt_to": dt_to, "tags": _kw(tags)},
        "qtd_assuntos": len(noticias), "noticias": noticias,
    }
    # =====================================================================
    # PRONTO PARA IA: 'payload' já respeita aba, filtros de tempo, tags e o
    # agrupamento de relevância. No futuro, enviar para o modelo, ex.:
    #
    #   prompt = ("Você é um analista. Gere um resumo executivo detalhado das "
    #             "notícias a seguir, agrupando por tema e destacando o que mudou:\n"
    #             + json.dumps(payload, ensure_ascii=False))
    #   resumo = chamar_modelo(prompt)   # Ollama / OpenAI / etc.
    #   return {"payload": payload, "resumo": resumo}
    # =====================================================================
    return {"payload": payload, "resumo": None, "pronto_para_ia": True}

@app.post("/api/collect")
def post_collect():
    r = collector.collect_all()
    try: r["ai"] = pipeline.process_pending()
    except Exception as e: r["ai_error"] = str(e)
    return r

# ---------- IA: análise sob demanda + configuração de provedor ----------
@app.post("/api/process")
def post_process(): return pipeline.process_pending()
@app.post("/api/reprocess")
def post_reprocess(): return {"requeued": db.requeue_all(), "pending": db.count_pending()}
@app.get("/api/ai-config")
def get_ai_cfg():
    c = db.get_ai_config()
    return {"provider": c.get("provider"), "model": c.get("model"), "base_url": c.get("base_url"),
            "has_key": bool((c.get("api_key") or "").strip()), "active": ai_factory.active_label(),
            "pending": db.count_pending()}
@app.put("/api/ai-config")
def put_ai_cfg(cfg: AiConfigIn):
    key = cfg.api_key.strip()
    if not key:                              # campo vazio = manter a chave atual
        key = (db.get_ai_config().get("api_key") or "")
    db.set_ai_config(cfg.provider, cfg.model, key, cfg.base_url)
    return {"ok": True, "active": ai_factory.active_label()}
@app.post("/api/ai-test")
def ai_test():
    p = ai_factory.get_provider()
    info = {"engine": getattr(p, "name", "?"), "model": getattr(p, "model", "?")}
    try:
        info.update({"ok": True, "message": p.ping()})
    except Exception as e:
        info.update({"ok": False, "message": f"{type(e).__name__}: {str(e)[:400]}"})
    return info

# ---------- lixeira/spam por aba ----------
@app.post("/api/tabs/{tid}/spam")
def post_spam(tid: int, s: SpamIn):
    hashes = []
    for aid in s.ids:
        a = db.get_article(aid)
        if a and a.get("url"): hashes.append(db.url_hash(a["url"]))
    return {"ok": True, "added": db.add_spam(tid, hashes)}

@app.get("/api/stats")
def stats():
    return {"total": db.count_articles(), "sources": len(db.list_sources(active_only=True)),
            "tabs": len(db.list_tabs()), "interval_min": config.COLLECT_INTERVAL_MIN,
            "proxy": bool(config.NEWS_PROXY), "pending": db.count_pending(),
            "ai": ai_factory.active_label()}

@app.get("/")
def index(): return FileResponse(STATIC_DIR / "index.html")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Entrypoint: rode `python run.py` (ou `uvicorn app:app`) — veja run.py na raiz.
