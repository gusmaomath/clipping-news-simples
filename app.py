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

import config, db, collector, clustering
from matching import matches_any_word, matches_any_sub

STATIC_DIR = pathlib.Path(__file__).parent / "static"
scheduler = BackgroundScheduler()
_NL = re.compile(r"\n{3,}")

def _auto():
    try:
        r = collector.collect_all(); print(f"[coleta] +{r['added']} | bloqueadas {r['blocked']} | dup {r['duplicates']}")
    except Exception as e:
        print("[coleta] erro:", e)

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
    name: str; preferences: str = ""; blacklist: str = ""
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
def put_tab(tid: int, t: TabIn): db.update_tab(tid, t.name, t.preferences, t.blacklist); return {"ok": True}
@app.post("/api/tabs/{tid}/move/{d}")
def move_tab(tid: int, d: int): db.move_tab(tid, 1 if d > 0 else -1); return {"ok": True}
@app.delete("/api/tabs/{tid}")
def del_tab(tid: int, purge: int = 0):
    removed = _purge_exclusive_articles(tid) if purge else 0
    db.delete_tab(tid)
    return {"ok": True, "removed_articles": removed}

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

def _build_feed(tab, q, since_hours, date_s, from_s, to_s, tag_filter, group=True):
    tabs = db.list_tabs()
    if not tabs:
        return {"no_tabs": True, "clusters": [], "available_tags": []}
    tabs_by_id = {t["id"]: t for t in tabs}
    # escopo: aba específica ou "Todas" (união do que passou em qualquer aba)
    arts = db.list_articles(limit=3000)
    links = db.article_tab_links()   # {tab_id: set(article_ids)} trazidos pelas buscas das abas
    if tab.strip().isdigit() and int(tab) in tabs_by_id:
        t = tabs_by_id[int(tab)]
        scope = [a for a in arts if _belongs(a, t, links)]
        tagdefs = db.list_tags(tab_id=t["id"])
    else:  # Todas
        scope = [a for a in arts if any(_belongs(a, t, links) for t in tabs)]
        tagdefs = db.list_tags()  # união das tags de todas as abas
    ql = q.strip().lower()
    sel = []
    for a in scope:
        if not _time_ok(a, since_hours, date_s, from_s, to_s): continue
        if ql and ql not in ((a.get("title") or "") + " " + (a.get("snippet") or "")).lower(): continue
        a["tags"] = _article_tags(a, tagdefs)
        if tag_filter and not (set(tag_filter) & set(a["tags"])): continue
        sel.append(a)
    # nomes de tags disponíveis (para o multi-select)
    available = sorted({t["name"] for t in tagdefs})
    if group:
        clusters = clustering.cluster(sel)
        clusters.sort(key=lambda c: c["newest"], reverse=True)
    else:
        clusters = [{"lead": a, "others": [], "size": 1, "sources": [a.get("source_name")],
                     "newest": a.get("published_at")} for a in sel]
    return {"no_tabs": False, "clusters": clusters, "available_tags": available}

# ---------- feed ----------
@app.post("/api/articles/delete")
def delete_articles_ep(b: IdsIn):
    return {"ok": True, "removed": db.delete_articles(b.ids)}

@app.get("/api/articles")
def get_articles(tab: str = "", q: str = "", since_hours: float = 0, date: str = "",
                 dt_from: str = "", dt_to: str = "", tags: str = "", group: int = 1):
    tag_filter = _kw(tags)
    res = _build_feed(tab, q, since_hours, date, dt_from, dt_to, tag_filter, group=bool(group))
    res["count"] = len(res["clusters"])
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
def post_collect(): return collector.collect_all()
@app.get("/api/stats")
def stats():
    return {"total": db.count_articles(), "sources": len(db.list_sources(active_only=True)),
            "tabs": len(db.list_tabs()), "interval_min": config.COLLECT_INTERVAL_MIN,
            "proxy": bool(config.NEWS_PROXY)}

@app.get("/")
def index(): return FileResponse(STATIC_DIR / "index.html")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    db.init_db()
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
