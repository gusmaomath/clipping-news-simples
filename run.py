"""Ponto de entrada do Clipping News. Rode: python run.py"""
import uvicorn

from clipping import db

if __name__ == "__main__":
    db.init_db()
    print("Clipping News em http://localhost:8000")
    uvicorn.run("clipping.main:app", host="127.0.0.1", port=8000, reload=False)
