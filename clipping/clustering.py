"""Agrupa notícias de sites diferentes sobre o mesmo assunto.
Mostra uma representativa e esconde as redundantes (com contagem de fontes)."""
import re
from datetime import datetime, timezone
from .matching import norm

_WORD = re.compile(r"[a-z0-9]+")
STOP = set("""a o as os um uma de do da dos das e ou que se na no nas nos para por com sem
sob sobre ao aos como mais menos ja nao sim ele ela apos antes the of to and in is it for on
that this with as are was be by an or from at diz pode vai ter sera foi tem novo nova""".split())

def tokens(text):
    return {w for w in _WORD.findall(norm(text)) if len(w) >= 4 and w not in STOP}

def overlap(a, b):
    if not a or not b: return 0.0
    return len(a & b) / min(len(a), len(b))

def _recency(a):
    iso = a.get("published_at") or a.get("fetched_at")
    if not iso: return 0.0
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        h = (datetime.now(timezone.utc) - d).total_seconds() / 3600
        return max(0.0, 72 - h)
    except Exception:
        return 0.0

def cluster(articles, threshold=0.5):
    groups = []  # {"tokens":[set..], "members":[..]}
    for a in articles:
        tk = tokens((a.get("title") or "") + " " + (a.get("snippet") or ""))
        best_i, best = -1, 0.0
        for i, g in enumerate(groups):
            ov = max((overlap(tk, mt) for mt in g["tokens"]), default=0.0)
            if ov > best: best, best_i = ov, i
        if best_i >= 0 and best >= threshold:
            groups[best_i]["members"].append(a); groups[best_i]["tokens"].append(tk)
        else:
            groups.append({"tokens": [tk], "members": [a]})
    out = []
    for g in groups:
        members = sorted(g["members"], key=_recency, reverse=True)
        lead = members[0]
        sources = sorted({m.get("source_name") for m in members if m.get("source_name")})
        out.append({"lead": lead, "others": members[1:], "size": len(members),
                    "sources": sources, "newest": lead.get("published_at") or lead.get("fetched_at") or ""})
    return out
