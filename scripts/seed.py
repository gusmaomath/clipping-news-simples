"""Cria fontes e abas de exemplo (com preferências e tags). Rode: python scripts/seed.py
A aba 'Todas' aparece automaticamente quando existe ao menos uma aba."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from clipping import db

SOURCES = [
    ("InfoMoney – Mercados", "rss", "https://www.infomoney.com.br/mercados/feed/"),
    ("InfoMoney – Economia", "rss", "https://www.infomoney.com.br/economia/feed/"),
    ("Money Times – Mercados", "rss", "https://www.moneytimes.com.br/mercados/feed/"),
    ("Busca: Ibovespa B3", "google_news", "ibovespa OR B3 bolsa"),
    ("Busca: renda fixa", "google_news", "renda fixa tesouro direto"),
]
# (nome, preferences, blacklist, [(tag, keywords)...])
TABS = [
    ("Geral", "", "boato, sorteio", [
        ("Mercado", "dinheiro, taxa, banco, bolsa"),
        ("Juros", "selic, juros, copom"),
    ]),
    ("Renda Fixa", "renda fixa, tesouro, cdb, debênture, lci, lca", "", [
        ("Debênture", "debenture, duration"),
        ("Tesouro", "tesouro, prefixado, ipca"),
    ]),
]

def main():
    db.init_db()
    have = {(s["name"], s["value"]) for s in db.list_sources()}
    for n, t, v in SOURCES:
        if (n, v) not in have:
            db.add_source(n, t, v); print("+ fonte:", n)
    existing = {t["name"] for t in db.list_tabs()}
    for name, pref, bl, tags in TABS:
        if name in existing: continue
        tid = db.add_tab(name, pref, bl); print("+ aba:", name)
        for tg, kw in tags:
            db.add_tag(tid, tg, kw); print("    tag:", tg)
    print("\nPronto. Agora rode:  python run.py")

if __name__ == "__main__":
    main()
