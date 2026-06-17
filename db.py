"""Banco: fontes, abas (preferências/blacklist), tags por aba e notícias.
Deduplicação por hash de URL. Guarda a data ORIGINAL de publicação."""
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tabs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    preferences TEXT NOT NULL DEFAULT '',   -- palavras que priorizam/incluem
    blacklist  TEXT NOT NULL DEFAULT '',     -- palavras que excluem
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tab_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tab_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tab_searches (        -- buscas Google News POR ABA
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tab_id INTEGER NOT NULL,
    term TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS article_tabs (        -- vínculo notícia -> aba (busca da aba)
    article_id INTEGER NOT NULL,
    tab_id INTEGER NOT NULL,
    PRIMARY KEY (article_id, tab_id)
);
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    url_hash TEXT NOT NULL UNIQUE,           -- trava de deduplicação
    source_id INTEGER, source_name TEXT,
    snippet TEXT, content TEXT,
    published_at TEXT,                       -- data/hora ORIGINAL da publicação
    fetched_at TEXT NOT NULL,
    image_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at DESC);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Sites RSS pré-cadastrados no primeiro uso (fontes globais).
DEFAULT_SOURCES = [
    ("G1",                 "https://g1.globo.com/rss/g1/"),
    ("InfoMoney",          "https://www.infomoney.com.br/feed/"),
    ("Valor (mais lidas)", "https://valor.globo.com/rss/"),
    ("Folha - Mercado",    "https://feeds.folha.uol.com.br/mercado/rss091.xml"),
    ("Agência Brasil",     "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
    ("BBC News Brasil",    "https://www.bbc.com/portuguese/index.xml"),
    ("CNN Brasil",         "https://www.cnnbrasil.com.br/feed/"),
    ("Exame",              "https://exame.com/feed/"),
]

def url_hash(url):
    return hashlib.sha1((url or "").strip().lower().encode("utf-8")).hexdigest()

@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn; conn.commit()
    finally:
        conn.close()

def _cols(c, t): return {r[1] for r in c.execute(f"PRAGMA table_info({t})")}

def init_db():
    with get_conn() as c:
        c.executescript(SCHEMA)
        # migração de versões antigas (tabs com include_kw/exclude_kw)
        tc = _cols(c, "tabs")
        if "include_kw" in tc and "preferences" in tc:
            c.execute("UPDATE tabs SET preferences=include_kw WHERE preferences=''")
            c.execute("UPDATE tabs SET blacklist=exclude_kw WHERE blacklist=''")
        # semeia sites RSS padrão só uma vez (banco novo, sem fontes ainda)
        if not c.execute("SELECT 1 FROM meta WHERE key='seeded_defaults'").fetchone():
            if c.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0:
                for name, url in DEFAULT_SOURCES:
                    c.execute("INSERT INTO sources (name,type,value,active,created_at) VALUES (?,?,?,1,?)",
                              (name, "rss", url, now_iso()))
            c.execute("INSERT OR REPLACE INTO meta (key,value) VALUES ('seeded_defaults','1')")

def now_iso(): return datetime.now(timezone.utc).isoformat()

# ---- fontes ----
def list_sources(active_only=False):
    q = "SELECT * FROM sources" + (" WHERE active=1" if active_only else "") + " ORDER BY name COLLATE NOCASE"
    with get_conn() as c: return [dict(r) for r in c.execute(q).fetchall()]
def add_source(name, type_, value):
    with get_conn() as c:
        return c.execute("INSERT INTO sources (name,type,value,active,created_at) VALUES (?,?,?,1,?)",
                         (name.strip(), type_.strip(), value.strip(), now_iso())).lastrowid
def delete_source(sid):
    with get_conn() as c: c.execute("DELETE FROM sources WHERE id=?", (sid,))
def toggle_source(sid, active):
    with get_conn() as c: c.execute("UPDATE sources SET active=? WHERE id=?", (1 if active else 0, sid))

# ---- abas ----
def list_tabs():
    with get_conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tabs ORDER BY position, id").fetchall()]
def get_tab(tid):
    with get_conn() as c:
        r = c.execute("SELECT * FROM tabs WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None
def add_tab(name, preferences="", blacklist=""):
    with get_conn() as c:
        nxt = c.execute("SELECT COALESCE(MAX(position),0)+1 FROM tabs").fetchone()[0]
        return c.execute("INSERT INTO tabs (name,preferences,blacklist,position,created_at) VALUES (?,?,?,?,?)",
                         (name.strip(), preferences.strip(), blacklist.strip(), nxt, now_iso())).lastrowid
def update_tab(tid, name, preferences, blacklist):
    with get_conn() as c:
        c.execute("UPDATE tabs SET name=?, preferences=?, blacklist=? WHERE id=?",
                  (name.strip(), preferences.strip(), blacklist.strip(), tid))
def move_tab(tid, d):
    with get_conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM tabs ORDER BY position, id").fetchall()]
        if tid not in ids: return
        i = ids.index(tid); j = i + d
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for pos, x in enumerate(ids): c.execute("UPDATE tabs SET position=? WHERE id=?", (pos, x))
def delete_tab(tid):
    with get_conn() as c:
        c.execute("DELETE FROM tabs WHERE id=?", (tid,))
        c.execute("DELETE FROM tab_tags WHERE tab_id=?", (tid,))
        c.execute("DELETE FROM tab_searches WHERE tab_id=?", (tid,))
        c.execute("DELETE FROM article_tabs WHERE tab_id=?", (tid,))

# ---- buscas Google News por aba ----
def list_searches(tab_id):
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM tab_searches WHERE tab_id=? ORDER BY id", (tab_id,)).fetchall()]
def list_all_searches():
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM tab_searches WHERE active=1").fetchall()]
def add_search(tab_id, term):
    with get_conn() as c:
        return c.execute("INSERT INTO tab_searches (tab_id,term,active,created_at) VALUES (?,?,1,?)",
                         (tab_id, term.strip(), now_iso())).lastrowid
def delete_search(sid):
    with get_conn() as c: c.execute("DELETE FROM tab_searches WHERE id=?", (sid,))

# ---- vínculo notícia <-> aba ----
def link_article_tab(article_id, tab_id):
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO article_tabs (article_id,tab_id) VALUES (?,?)",
                  (article_id, tab_id))
def article_tab_links():
    """Devolve {tab_id: set(article_ids)} das notícias trazidas pelas buscas das abas."""
    out = {}
    with get_conn() as c:
        for r in c.execute("SELECT tab_id, article_id FROM article_tabs").fetchall():
            out.setdefault(r["tab_id"], set()).add(r["article_id"])
    return out

# ---- tags (por aba) ----
def list_tags(tab_id=None):
    q = "SELECT * FROM tab_tags"; p = []
    if tab_id is not None:
        q += " WHERE tab_id=?"; p.append(tab_id)
    q += " ORDER BY name COLLATE NOCASE"
    with get_conn() as c:
        return [dict(r) for r in c.execute(q, p).fetchall()]
def add_tag(tab_id, name, keywords):
    with get_conn() as c:
        return c.execute("INSERT INTO tab_tags (tab_id,name,keywords,created_at) VALUES (?,?,?,?)",
                         (tab_id, name.strip(), keywords.strip(), now_iso())).lastrowid
def update_tag(tag_id, name, keywords):
    with get_conn() as c:
        c.execute("UPDATE tab_tags SET name=?, keywords=? WHERE id=?", (name.strip(), keywords.strip(), tag_id))
def delete_tag(tag_id):
    with get_conn() as c: c.execute("DELETE FROM tab_tags WHERE id=?", (tag_id,))

# ---- artigos ----
def exists_hash(h):
    with get_conn() as c:
        return c.execute("SELECT 1 FROM articles WHERE url_hash=? LIMIT 1", (h,)).fetchone() is not None
def insert_article(a):
    """Insere e devolve o id (ou None se já existia)."""
    h = url_hash(a["url"])
    with get_conn() as c:
        try:
            cur = c.execute("INSERT INTO articles (title,url,url_hash,source_id,source_name,snippet,published_at,fetched_at,image_url) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (a["title"], a["url"], h, a.get("source_id"), a.get("source_name"),
                       a.get("snippet"), a.get("published_at"), now_iso(), a.get("image_url")))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None
def article_id_by_hash(h):
    with get_conn() as c:
        r = c.execute("SELECT id FROM articles WHERE url_hash=?", (h,)).fetchone()
        return r["id"] if r else None
def list_articles(limit=2000):
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM articles ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?", (limit,)).fetchall()]
def get_article(aid):
    with get_conn() as c:
        r = c.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None
def set_content(aid, content):
    with get_conn() as c:
        c.execute("UPDATE articles SET content=? WHERE id=?", (content, aid))
def count_articles():
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
def delete_articles(ids):
    ids = list(ids)
    if not ids: return 0
    with get_conn() as c:
        c.executemany("DELETE FROM articles WHERE id=?", [(i,) for i in ids])
        c.executemany("DELETE FROM article_tabs WHERE article_id=?", [(i,) for i in ids])
    return len(ids)
