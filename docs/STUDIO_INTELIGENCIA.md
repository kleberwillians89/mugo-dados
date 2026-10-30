# Mugô Studio — inteligência, motores, aprovação, WhatsApp e Mídia On

## 1. Inteligência de dados (base de tudo)

`server/services/studio_intelligence.py` monta, para cada empresa, um pacote com o que o Dados **já tem**:

| Fonte | O que entra |
|---|---|
| Perfil da marca e contexto do negócio | tom, público, pilares, palavras proibidas, restrições, segmento, diferenciais |
| Snapshot da Inteligência (90 dias) | KPIs (faturamento, pedidos, ticket, investimento, ROAS real, CPA, sessões, conversão…), campanhas que mais investiram com receita e ROAS, funil do site |
| Instagram | posts que mais e menos alcançaram em relação ao próprio formato (com trecho da legenda) |
| Melhores horários | dias e faixas de maior alcance |
| Metas e última análise | metas do mês com progresso; mudança principal, oportunidade e ação prioritária |
| **Aprendizado com o cliente** | pautas que o cliente aprovou (referência de tom) e os ajustes que ele pediu (o que evitar) |

- Cada fonte tem limite de 12 s; a que falhar vira **lacuna** e o resto segue.
- Texto com cara de e-mail, CPF/CNPJ ou telefone é descartado (mesmo filtro do MCP).
- Cache de 10 min por empresa. Toda resposta de IA volta com `based_on` ("com base em 42 posts, 4 aprovações…").

## 2. Motores de conteúdo (trazidos do iAgência)

| Motor no iAgência | Onde está no Dados |
|---|---|
| `creative_guidance.py` + regras de ouro | `studio_llm.CREATIVE_GUIDANCE`, aplicado a **todo** texto gerado, inclusive o calendário |
| `feedback.py` (exemplos aprovados) | `approval_learnings` → entra no calendário e em todos os motores |
| `copywriting_logic.py` (Redator) | Modal da pauta → **Legenda final** e **Revisar** |
| `social_agent.py` / `video_logic.py` | **3 variações**, **5 ganchos**, **Hashtags**, **Roteiro de Reels** |
| `planning_agent.py` (Head de Estratégia) | Calendário → **Estratégia (IA)**: chat com o mês e os dados |
| Brand Manager + `reference_files.py` | Perfil da marca → **Sugerir perfil com IA** (lê o guia em PDF da Biblioteca) |

- Nada é salvo sem a pessoa clicar em "Usar" ou "Salvar".
- Clichês e palavras proibidas do perfil aparecem como alerta.
- Teto de 20 chamadas de IA por minuto por empresa.
- Mesma chave e mesmo modelo da Inteligência (`OPENAI_API_KEY`, `OPENAI_MODEL`).
- `pypdf` passou para o `requirements.txt` (é usado em produção para ler o guia).

## 3. Menu Aprovação (`/aprovacao`)

O menu Comercial do CRM virou a área de aprovação de conteúdo:

- **Funil:** Rascunho → Revisão interna → Com o cliente → Ajuste pedido → Aprovado → **Publicado**.
  Arrastar a pauta muda o status. "Com o cliente" só acontece quando o link é enviado.
- **Pedidos:** links enviados, prazo, último lembrete; lembrete pelo WhatsApp reenvia o **mesmo** link.
- **Contatos:** quem aprova e o que recebe (conteúdo, tráfego, resultados), com um contato principal.
- **Mensagens:** agenda da semana, relatório de tráfego (7 dias) e resultados do mês, com prévia e histórico.

## 4. WhatsApp da Mugô (MugôZap)

O envio continua no CRM. O Dados chama o `mugozap-api` pelo caminho interno que já existe
(`X-Task-Command-Worker-Key` + membro da equipe). Os textos dos templates e o passo a passo de
cadastro estão em **`docs/WHATSAPP_TEMPLATES.md`**.

- **Números:** sempre do painel.
- **IA:** escreve só a frase de destaque ou atenção, a partir desses números; a equipe pode editar antes de enviar.
- **Sem as variáveis `MUGOZAP_*`:** o Dados gera o link `wa.me` com o mesmo texto.
- **Idempotência:** a mesma mensagem não sai duas vezes no mesmo dia (o CRM também confere).

## 5. Mídia On (`/midia`): estratégia calculada com os dados

`server/services/media_strategy.py` monta a estratégia do mês e a IA só escreve a leitura em cima dos números:

1. **Diagnóstico por canal:** Meta Ads e Google Ads, últimos 30 dias vs os 30 anteriores, com achados objetivos:
   fadiga de criativo (CPM sobe e CTR cai), limite de escala (verba sobe e ROAS cai), verba sem conversão,
   oportunidade de escalar.
2. **Curva de retorno de cada canal:** y = a·gasto^b, ajustada nas 13 semanas mais recentes. O b é **medido** quando a
   verba variou e o ajuste explica pelo menos 30% da variação; senão, usa uma referência conservadora e a curva aparece
   como "estimada".
3. **Divisão ótima da verba:** maximiza o resultado do objetivo (receita, conversões, cliques ou impressões). Limites:
   - mínimo de 5% para canal ativo;
   - teto de 40% para canal com poucos dados;
   - no máximo 2,5x o investimento atual do canal, ou 1,5x quando a curva é estimada.
4. **Cenários de verba:**
   - **Ritmo atual.**
   - **Bater a meta:** usa a meta de faturamento do mês e a elasticidade medida; teto de 3x.
   - **Limite de eficiência:** onde o próximo R$ 1 deixa de devolver o mínimo; usa a margem de contribuição, se informada.
   - **Verba definida pela equipe.**
5. **O que fazer em cada campanha:** escalar, manter, otimizar, pausar ou aprender, com o motivo em números.
6. **Calendário de investimento:** semanas com peso maior antes das datas comerciais (Black Friday, Natal, Dia das
   Mães…) e das datas da marca.
7. **Impulsionamento cruzado com o calendário editorial:**
   - **Verba:** 20% da verba de Meta é reservada para impulsionar as pautas com mais chance de resultado.
   - **Escolha das pautas:** formato que mais alcança na conta, semanas de pico ou aquecimento, pauta de data sazonal e status.
   - **Início:** 24 h depois de publicar; no dia da publicação em semana de pico. Duração de 7 dias.
   - **No Calendário:** com o plano salvo, essas pautas ganham ⚡ e o modal mostra as datas e a verba.
8. **Limites para a operação:** verba diária, CPA alvo e máximo, ROAS alvo e mínimo (equilíbrio pela margem).
9. **Leitura da IA:** tese, papel de cada canal, notas por campanha (só campanhas da lista), criativos, riscos e
   próximos 7 dias.
10. **Plano salvo:** guarda a estratégia congelada. O planejado x realizado compara o ritmo e o CPA/ROAS com os alvos.

A equipe pode ajustar a divisão: a projeção é recalculada na hora pelas mesmas curvas.

## Para ligar em produção (Kleber)

1. Aplicar, nesta ordem, no SQL Editor:
   - `20261104_000053_studio_approval_flow.sql` (status publicado, contatos, mensagens, lembrete)
   - `20261105_000054_media_plans.sql` (planos do Mídia On)
   - `20261106_000055_media_plan_strategy.sql` (estratégia congelada no plano)

   O backend tolera a 053 ainda não aplicada no envio de links, mas contatos, mensagens e o status
   "publicado" só funcionam depois dela.
2. Deploy no Render (o `pypdf` será instalado pelo `requirements.txt`).
3. WhatsApp: seguir `docs/WHATSAPP_TEMPLATES.md` (templates na Meta, variáveis `MUGOZAP_*` e `FRONTEND_URL`).
4. Para o lembrete reenviar o link, o backend precisa de `TOKEN_ENCRYPTION_KEY` (já usada para os
   tokens da Meta). Pedidos criados antes deste deploy não têm o link guardado e pedem um link novo.
