"""Instruções de análise enviadas ao modelo (a PERSONA da aba é anexada a isto)."""

INSTRUCOES = """Você é um analista de clipping de notícias. Para a notícia fornecida, \
considerando a PERSONA e as TAGS da seção, produza uma análise estruturada:

- relevant: true se a notícia for útil para a persona; false se for irrelevante/ruído.
- score: número de 0 a 100 medindo a UTILIDADE/relevância para a persona (100 = essencial, 0 = inútil).
- sentiment: exatamente um de [Positivo, Neutro, Negativo, Risco, Oportunidade], sob a ótica da \
utilidade daquela informação para a persona (não o tom da manchete).
- title_t: o título reescrito de forma clara e TRADUZIDO para IDIOMA_SAIDA.
- summary_t: um resumo DETALHADO e completo, de 1 a 3 parágrafos (5 a 10 frases), no IDIOMA_SAIDA. \
Cubra: o que aconteceu, os fatos e números concretos (valores, datas, percentuais), nomes de \
pessoas/empresas/lugares envolvidos, o contexto necessário para entender e por que isso importa \
para a persona. Use SOMENTE informações presentes no texto — não invente nada. Quanto mais \
informativo e fiel ao texto original, melhor.

Se a notícia já estiver no IDIOMA_SAIDA, ainda assim reescreva o resumo de forma detalhada e clara.
Responda somente no formato estruturado solicitado."""

# Para provedores via REST (OpenAI/Gemini): força um objeto JSON com chaves exatas.
JSON_HINT = ('\n\nResponda APENAS um objeto JSON, sem texto fora dele, com as chaves exatas: '
             '{"relevant": boolean, "score": number (0-100), '
             '"sentiment": "Positivo"|"Neutro"|"Negativo"|"Risco"|"Oportunidade", '
             '"title_t": string, "summary_t": string}.')

def build_payload(persona, lang, tags, title, text):
    """Devolve (system_text, user_text) usados por todos os provedores."""
    system = (INSTRUCOES + "\n\nIDIOMA_SAIDA: " + (lang or "pt-BR")
              + "\nTAGS: " + ", ".join(tags or [])
              + "\n\nPERSONA:\n" + (persona or "(sem persona definida — use bom senso jornalístico)"))
    user = f"TÍTULO: {title}\n\nTEXTO:\n{(text or '')[:16000]}"
    return system, user
