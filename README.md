# Clipping News

Painel de clipping de notícias: coleta de RSS/Google News, abas por setor com filtros
e tags próprias, agrupamento de notícias do mesmo assunto, busca global, leitura em
popup e tema claro/escuro. Preparado para receber IA no futuro.

## Como rodar

```bash
cd clipping-news-simples
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py        # fontes + abas de exemplo (Geral, Renda Fixa) com tags
python app.py         # http://localhost:8000
```

Clique em **Coletar** para a primeira carga (também roda a cada 30 min).

## Coleta (scraper)

- **Volume**: puxa até **300** notícias por fonte por execução (`NEWS_MAX_PER_SOURCE`).
- **Recência estrita**: salva **apenas notícias da semana atual** (segunda 00:00 → agora).
- **Data original**: guarda a data/hora **de publicação** da notícia, não a da coleta.
- **Dedup definitivo**: trava por **hash de URL** — a mesma notícia nunca é salva duas vezes.
- **Blacklist pré-banco**: as palavras de blacklist das abas são aplicadas **durante a coleta**;
  o que é bloqueado **não entra** no banco.
- **Proxy**: defina `NEWS_PROXY` (ex.: `http://user:senha@host:porta`) para rotear as
  requisições do scraper por um proxy.

## Abas, filtros e tags

- A aba **Todas** só aparece **depois que você cria a primeira aba** (mostra a união do que
  passou pelos filtros das abas).
- **Agrupamento de relevância**: notícias de sites diferentes sobre o mesmo tema viram um
  só card; as redundantes ficam em **"Ver outras X fontes"**.
- Cada aba tem sua própria config: **Preferências** (priorizam/incluem), **Blacklist**
  (excluem) e **Tags** (categorizador por palavras-chave, ex.: `Mercado` → `dinheiro, taxa, banco`).
  O casamento de tags **ignora acentos e maiúsculas**.
- **Filtros de tempo** na aba: Tudo, 1h, 2h, dia específico e período (range de datas/horas).
- As **tags** aparecem como filtros clicáveis e como etiquetas nos cards.

## Interface

- **Tema claro/escuro** com a cor base **#800000** (botão ◐/☀ no topo; preferência salva).
- **Busca global** no topo pesquisa qualquer notícia salva; clicar abre em **popup**.
- Clicar numa notícia abre o **popup** com o texto completo (extraído sob demanda).
- **Resumo Executivo**: botão na aba que consolida as notícias exibidas (respeitando
  filtros de tempo, tags e agrupamento) num **payload pronto para IA**.

## IA (futuro)

- `collector.py` tem **stubs comentados** marcando onde plugar a IA para ler o texto inteiro,
  resumir e fazer **filtragem semântica** antes de salvar.
- A rota `/api/resumo-executivo` já devolve o **payload consolidado** e tem o trecho
  comentado de onde enviar ao modelo (Ollama/OpenAI) para gerar o resumo detalhado.

## Variáveis de ambiente

| Variável | Padrão | O que faz |
|---|---|---|
| `NEWS_PROXY` | (vazio) | Proxy HTTP do scraper |
| `NEWS_MAX_PER_SOURCE` | `300` | Notícias por fonte por coleta |
| `COLLECT_INTERVAL_MIN` | `30` | Minutos entre coletas |
| `NEWS_MAX_WORKERS` | `10` | Fontes em paralelo |
| `NEWS_HL`/`NEWS_GL`/`NEWS_CEID` | pt-BR/BR/... | Idioma/região do Google News |
| `NEWS_DB` | `news.db` | Caminho do banco |

## Estrutura

```
clipping-news-simples/
  app.py          API (abas, tags, tempo, agrupamento, busca, resumo)
  collector.py    scraper (proxy, recência, dedup, blacklist pré-banco, stubs de IA)
  clustering.py   agrupamento de notícias do mesmo assunto
  matching.py     casamento de termos (ignora acento/maiúsculas)
  db.py           SQLite (fontes, abas, tags, notícias)
  config.py       configurações
  seed.py         dados de exemplo
  static/index.html  interface (tema, filtros, tags, popup, resumo)
```
