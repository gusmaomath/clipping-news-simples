# Clipping News

Agregador de notícias com **análise por IA**: coleta de RSS e Google News, agrupamento de matérias sobre o mesmo evento, e — guiado por uma **persona** que você define por seção — relevância, **score**, **sentimento** e **tradução** de título/resumo. Tudo numa interface web única (FastAPI + SQLite + JS puro).

A IA é **modular**: Claude, GPT (OpenAI) ou Gemini (Google). Sem chave, roda em **modo heurístico** offline.

---

## Estrutura de pastas

```
clipping-news-simples/
├─ run.py                 # ponto de entrada → python run.py
├─ app.py                 # atalho de compatibilidade (uvicorn app:app)
├─ requirements.txt
├─ README.md
├─ news.db                # banco SQLite (criado no 1º uso)
│
├─ clipping/              # PACOTE DA APLICAÇÃO
│  ├─ __init__.py
│  ├─ main.py             # FastAPI + todos os endpoints + montagem do feed
│  ├─ config.py           # configurações por variável de ambiente
│  ├─ db.py               # SQLite: fontes, abas, tags, buscas, notícias, IA, spam
│  ├─ collector.py        # scraper RSS / Google News (status 'raw')
│  ├─ pipeline.py         # worker de IA: texto integral, dedup, análise por aba
│  ├─ clustering.py       # agrupamento heurístico por similaridade de título
│  ├─ matching.py         # casamento de termos (sem acento, case-insensitive)
│  └─ ai/                 # camada de IA agnóstica de provedor
│     ├─ __init__.py
│     ├─ base.py          # tipo Analysis + lista de sentimentos
│     ├─ prompts.py       # instruções + montagem do payload
│     ├─ factory.py       # escolhe o provedor pela config salva
│     ├─ heuristic.py     # fallback offline (sem chave)
│     ├─ anthropic_provider.py   # Claude (SDK oficial)
│     ├─ openai_provider.py      # GPT (REST/httpx)
│     └─ gemini_provider.py      # Gemini (REST/httpx)
│
├─ static/
│  └─ index.html          # toda a interface (SPA em um arquivo)
│
└─ scripts/
   └─ seed.py             # cria fontes/abas de exemplo (opcional)
```

---

## Como rodar

```bash
# 1) dependências (inclui o SDK 'anthropic'; OpenAI/Gemini usam só httpx)
pip install -r requirements.txt

# 2) subir o app
python run.py
#    alternativa: uvicorn app:app --host 127.0.0.1 --port 8000

# 3) abrir
#    http://localhost:8000

# (opcional) dados de exemplo:
python scripts/seed.py
```

Na interface: **Coletar** puxa as notícias e já dispara a análise. Ou configure a IA em **⚙ → 🤖 IA** e use **✨ Analisar**. Alterou o front? Recarregue com **Ctrl+F5**.

---

## Configurar a IA (modular)

Em **⚙ Configurações → 🤖 IA**, escolha o provedor, o modelo e cole a chave.

| Provedor | Onde pegar a chave | Observações |
|---|---|---|
| **Gemini (Google)** | https://aistudio.google.com/apikey | Grátis no free tier. Modelos: `gemini-2.0-flash`, `gemini-1.5-flash/pro`. |
| **OpenAI (GPT)** | https://platform.openai.com/api-keys | Precisa de crédito. Modelos: `gpt-4o-mini`, `gpt-4o`. |
| **Anthropic (Claude)** | https://console.anthropic.com | Precisa de crédito + `pip install anthropic`. Modelos: `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`. |
| **Heurística** | — | Sem chave; score/sentimento por regras locais. |

Se nenhuma chave válida estiver configurada, o sistema usa a **heurística** automaticamente (nada quebra).

---

## Como funciona

1. **Coleta** (`collector.py`): baixa RSS (sites globais) + buscas do Google News (por aba), só da semana atual, deduplica por hash de URL e grava como `status='raw'`.
2. **Pipeline** (`pipeline.py`): para cada notícia nova — extrai o **texto integral**, atribui um **event_key** (mesmo evento) e, para cada aba a que ela pertence, chama o provedor de IA → grava em `article_ai` (relevância, score, sentimento, título/resumo traduzidos). Marca `status='ready'`.
3. **Feed** (`main.py`): monta o feed por aba aplicando filtros de tempo/tags/busca, esconde irrelevantes e itens na **lixeira** da aba, agrupa por evento e ordena por recência (Lista) ou por **score** (Portal).

### Recursos da interface
- **Abas (setores)** na barra lateral; cada uma com **Persona** (critério da IA), **Idioma**, Preferências, Blacklist, Tags e Buscas Google News.
- **Lista × Portal**: alterne no topo. Portal mostra **imagem** da notícia (quando houver) e ordena por score.
- **Paginação**: 20 por página no Portal, 15 na Lista.
- **Sentimento** colorido (Positivo/Neutro/Negativo/Risco/Oportunidade) + **score** no card.
- **Lixeira por aba**: no modo Editar, "Apagar" dentro de uma aba manda a notícia para a lixeira daquela aba (não reaparece nem é reprocessada). Em "Todas", apaga do banco.
- **Importar/Exportar** a configuração de uma aba (JSON) — botões no editor da aba e no topo das configurações.
- **Como usar** (botão no topo): guia + prompt pronto para gerar a configuração de uma aba com uma IA.

---

## Endpoints principais (API)

| Método | Rota | Função |
|---|---|---|
| GET | `/api/articles` | Feed (params: `tab,q,since_hours,date,tags,group,sort,page,per_page`) |
| GET | `/api/article/{id}` | Notícia completa (popup) |
| GET | `/api/search?q=` | Busca global |
| POST | `/api/collect` | Coleta + análise |
| POST | `/api/process` | Só análise da fila |
| GET/PUT | `/api/ai-config` | Provedor/modelo/chave de IA |
| ... | `/api/tabs...` | Abas (CRUD, mover, export/import) |
| POST | `/api/tabs/{id}/spam` | Enviar notícias para a lixeira da aba |
| ... | `/api/tags`, `/api/tabs/{id}/searches`, `/api/sources` | CRUD de tags, buscas e fontes |

---

## Variáveis de ambiente (config.py)

| Variável | Padrão | O que faz |
|---|---|---|
| `NEWS_DB` | `news.db` | Caminho do banco |
| `COLLECT_INTERVAL_MIN` | `30` | Intervalo da coleta automática |
| `NEWS_MAX_PER_SOURCE` | `50` | Máx. de notícias por fonte por execução |
| `NEWS_MAX_WORKERS` | `10` | Threads de coleta |
| `NEWS_PROXY` | `(vazio)` | Proxy opcional do scraper |
| `NEWS_HL` / `NEWS_GL` / `NEWS_CEID` | pt-BR / BR / BR:pt-419 | Localização do Google News |
