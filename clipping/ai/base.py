"""Tipos compartilhados da camada de IA."""
from dataclasses import dataclass

SENTIMENTS = ["Positivo", "Neutro", "Negativo", "Risco", "Oportunidade"]

@dataclass
class Analysis:
    relevant: bool          # passou no filtro semântico da persona
    score: float            # 0..100 utilidade/relevância
    sentiment: str          # um de SENTIMENTS
    title_t: str            # título traduzido/padronizado p/ idioma da aba
    summary_t: str          # resumo traduzido/padronizado

    def clamped(self):
        self.score = max(0.0, min(100.0, float(self.score or 0)))
        if self.sentiment not in SENTIMENTS:
            self.sentiment = "Neutro"
        return self
