"""Atalho de compatibilidade — permite `uvicorn app:app`.
O código real vive no pacote `clipping/` (veja clipping/main.py)."""
from clipping.main import app  # noqa: F401
