# Mugô Studio — como o calendário editorial é gerado

Botão **Gerar <mês> com IA** → `POST /api/clients/{id}/studio/calendar/generate` → `services/studio_calendar.generate_month`.

A geração tem duas metades com responsabilidades diferentes:

## 1. O código decide QUANDO e EM QUE FORMATO (sem IA)

| Decisão | De onde vem |
|---|---|
| **Quantos posts** | `posts_per_week` do Perfil da marca (padrão 3). |
| **Quais dias da semana** | `services/posting_times.py`: os posts dos últimos 180 dias (`ig_media`) recebem um *índice de alcance* = alcance do post ÷ mediana de alcance do **mesmo formato**. Os dias com maior índice mediano (com pelo menos 2 posts de amostra) vencem. Sem histórico: ter, qui, qua, seg, sex, sáb, dom. |
| **Horário** | A melhor faixa de 3h daquele dia (mesmo cálculo). Dentro da faixa, a hora com mais **seguidores online** (`ig_online_followers`, coleta diária da Meta). Sem dado: início da faixa + 1h; sem nada: 19h. |
| **Formato** | Os formatos habilitados no perfil, ordenados pelo **alcance mediano real** de cada um na conta, em rodízio 50% / 30% / 20%. |
| **Datas especiais** | `services/studio_dates.py`: datas comerciais do Brasil calculadas (Páscoa, Carnaval, Dia das Mães/Pais, Black Friday, Cyber Monday, Natal…) + datas próprias do perfil. Datas comerciais e da marca ganham um post no dia. |
| **O que não é tocado** | Pautas aprovadas, em revisão ou criadas à mão continuam, e o dia delas não recebe outra. Só os rascunhos antigos da IA são trocados — e só depois que a IA respondeu. |

## 2. A IA decide O QUÊ (OpenAI, mesma chave da Inteligência)

Modelo: `OPENAI_MODEL` (padrão `gpt-4.1-mini`), temperatura 0,5, saída em JSON com schema estrito.

**Contexto enviado** (`build_prompt`):

- Perfil da marca: tom de voz, personalidade, público, pilares com peso, palavras a usar/evitar, hashtags, restrições.
- Contexto do negócio (o mesmo da Inteligência): segmento, produto, público, posicionamento, objetivos.
- Até 8 posts que mais performaram nos últimos 90 dias (formato, índice de alcance, 220 caracteres da legenda).
- Datas do mês.
- Até 10 assuntos em alta no Brasil agora (feed RSS do Google Trends), cada um com link de fonte.
- A lista de slots (data, dia, hora, formato, data especial) já decidida pelo código.

**Instruções** (resumo fiel do prompt):

> Preencha UMA pauta para CADA slot. Não mude data, horário nem formato.
> pillar: exatamente um pilar do perfil, respeitando os pesos no mês · title: pauta específica desta marca ·
> hook: primeira frase/cena que para o scroll · caption_draft: legenda no tom da marca, com CTA e hashtags do perfil ·
> rationale: 1 frase do porquê · slot com data especial trata da data do jeito da marca ·
> trend_id só se o assunto em alta combinar de verdade (máx. 2 no mês) · nunca usar palavras a evitar nem ferir restrições ·
> não inventar números, resultados, depoimentos, preços ou promoções.

## 3. Validação antes de gravar (`validate_items`)

- Slot desconhecido ou repetido → descartado.
- Pilar fora do perfil → removido (avisado).
- Tendência sem fonte, ou além de 2 no mês → removida.
- Palavra a evitar no texto → pauta marcada para revisão (não apagada).
- Dias sem pauta válida → avisados na tela.

Tudo nasce **rascunho**. Aprovação: equipe no calendário, ou cliente pelo link `/aprovar/<token>` (sem login, 14 dias).
