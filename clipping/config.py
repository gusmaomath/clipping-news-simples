"""Configurações."""
import os
DB_PATH = os.environ.get("NEWS_DB", "news.db")
COLLECT_INTERVAL_MIN = int(os.environ.get("COLLECT_INTERVAL_MIN", "30"))
USER_AGENT = os.environ.get("NEWS_USER_AGENT", "ClippingNews/1.0")
REQUEST_TIMEOUT = int(os.environ.get("NEWS_TIMEOUT", "20"))
HL = os.environ.get("NEWS_HL", "pt-BR")
GL = os.environ.get("NEWS_GL", "BR")
CEID = os.environ.get("NEWS_CEID", "BR:pt-419")

# Volume: puxa até este limite por fonte por execução
MAX_PER_SOURCE = int(os.environ.get("NEWS_MAX_PER_SOURCE", "50"))
MAX_WORKERS = int(os.environ.get("NEWS_MAX_WORKERS", "10"))

# Proxy opcional para as requisições do scraper (ex.: http://user:pass@host:porta).
# Vazio = sem proxy. Use quando precisar rodar em outra rede.
NEWS_PROXY = os.environ.get("NEWS_PROXY", "").strip()
