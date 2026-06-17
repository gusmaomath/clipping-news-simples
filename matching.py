"""Casamento de termos. Tudo case-insensitive e SEM acento (normalizado)."""
import re
import unicodedata

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()

_wcache = {}
def _wrx(term):
    key = norm(term)
    rx = _wcache.get(key)
    if rx is None:
        rx = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)")
        _wcache[key] = rx
    return rx

# palavra inteira (para blacklist/preferências): "ia" não casa "refinaria"
def contains_word(text, term):
    term = (term or "").strip()
    return bool(norm(term)) and _wrx(term).search(norm(text)) is not None
def matches_any_word(text, terms):
    return any(contains_word(text, t) for t in terms)

# substring (para tags): mais flexível ("banco" casa "bancos", "bancário")
def contains_sub(text, term):
    t = norm(term).strip()
    return bool(t) and t in norm(text)
def matches_any_sub(text, terms):
    return any(contains_sub(text, t) for t in terms)
