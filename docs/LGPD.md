# LGPD — Registro das operações de tratamento (art. 37)

**Controladora/operadora:** AURUM INTELLIGENCE LTDA — CNPJ 63.072.471/0001-25 (marca Mugô, plataforma Mugoverso)
**Contato de privacidade:** privacidade@mugoagencia.com.br
**Encarregado (DPO):** _[definir nome]_
**Última revisão:** 16/11/2026

Este documento descreve, para auditoria e homologação, que dados a plataforma trata, por quê, com quem
compartilha, por quanto tempo guarda e como protege. Os textos públicos ficam em `src/pages/LegalPages.tsx`
(/privacidade, /termos-de-uso, /exclusao-de-dados, /protecao-de-dados).

## 1. Papéis

| Dado | Papel da Aurum | Quem é o controlador |
|---|---|---|
| Usuários da plataforma (equipe Mugô e equipe do cliente) | Controladora | Aurum |
| Dados que o cliente conecta ou envia (anúncios, redes, loja, compradores finais, documentos) | Operadora | Empresa cliente |

## 2. Inventário de tratamento

| # | Operação | Dados | Titulares | Base legal (art. 7º) | Onde fica | Retenção |
|---|---|---|---|---|---|---|
| 1 | Login e controle de acesso | nome, e-mail, papel, empresa | usuários | execução de contrato (V) | Supabase Auth | contrato + 90 dias |
| 2 | Registros de acesso e auditoria | IP, data/hora, ação | usuários | obrigação legal (II) — Marco Civil art. 15 | Supabase | 6 meses |
| 3 | Integrações de mídia (Meta Ads, Google Ads, TikTok, Pinterest, LinkedIn) | métricas agregadas de campanhas | — (dados de empresa) | execução de contrato | Supabase | contrato + 90 dias |
| 4 | Redes sociais (Instagram, TikTok) | posts, métricas, comentários e Direct recebidos | seguidores que comentam/escrevem | operador: instrução do cliente | Supabase | contrato + 90 dias |
| 5 | Loja (Shopify, FBits) | pedidos, itens, nome/contato/endereço de comprador | compradores finais | operador: instrução do cliente | Supabase | contrato + 90 dias |
| 6 | GA4 e Clarity | sessões, eventos e páginas (agregados) | visitantes (anônimos) | operador | Supabase | contrato + 90 dias |
| 7 | Conhecimento da marca | documentos e textos enviados (texto extraído; o arquivo não é guardado) | eventuais pessoas citadas | operador | Supabase | contrato + 90 dias |
| 8 | IA (Tira-dúvidas, conteúdo, briefing, esteira, clipping) | pergunta + contexto de negócio minimizado | usuários | execução de contrato | OpenAI (processamento) + histórico no Supabase | histórico: contrato + 90 dias |
| 9 | Pesquisa pública (Brave) | nome da marca, segmento e concorrentes (termos públicos) | — | legítimo interesse (IX) | não guardado no Brave | — |
| 10 | E-mail marketing e WhatsApp do cliente | contatos e mensagens | contatos do cliente | definida pelo cliente (em regra, consentimento) | Supabase + provedor de envio | contrato + 90 dias |
| 11 | Fornecedores do Evento | nome, categoria, contato comercial | contatos de fornecedores | execução de contrato | Supabase | contrato + 90 dias |
| 12 | Calendário Google | eventos (leitura) | participantes | operador | Supabase | contrato + 90 dias |

## 3. Minimização na IA (regras com teste automático)

- Texto com padrão de e-mail, telefone, CPF ou CNPJ é descartado antes de ir para a IA (`studio_intelligence.clean_text`).
- Compradores entram só agregados (totais do dia, ticket, origem); nunca a pessoa.
- Telefone, e-mail e nome de contato de fornecedores não vão para a IA (`studio_suppliers.suppliers_text`).
- A pesquisa web nunca recebe a pergunta, métricas ou documentos (`mugo_ia_web`).
- O cliente não recebe o que é só da equipe (alertas, briefings internos, tarefas).
- Testes: `server/tests/test_lgpd_ai_minimization.py`, `test_mugo_ia.py`, `test_event_radar_suppliers.py`.

## 4. Operadores e suboperadores

| Provedor | Uso | País |
|---|---|---|
| Supabase | autenticação e banco de dados | EUA (região do projeto) |
| Render | servidor da aplicação (API) | EUA |
| Vercel | site (frontend) | EUA/global |
| GitHub | código e rotinas agendadas | EUA |
| OpenAI | processamento de IA | EUA |
| Brave Search | pesquisa pública | EUA |
| Meta, Google, Shopify, FBits, TikTok, Pinterest, LinkedIn, Microsoft | integrações autorizadas | variados |

Transferência internacional: art. 33 da LGPD, com cláusulas e garantias contratuais dos provedores.

## 5. Direitos do titular (art. 18) e prazo

Canal: privacidade@mugoagencia.com.br. Resposta em até 15 dias (art. 19, II), após verificar identidade e
vínculo com a empresa. Pedidos de compradores finais são encaminhados à loja controladora.

## 6. Segurança

- Acesso autenticado e por papel; isolamento entre empresas validado no servidor em toda rota.
- Credenciais de integração criptografadas (`TOKEN_ENCRYPTION_KEY`); segredos nunca vão ao navegador.
- Tabelas com RLS ativo e acesso só pelo `service_role` no servidor.
- Logs públicos do GitHub não mostram dados (só comando, status e duração).
- Incidentes: comunicação à ANPD e aos titulares em prazo razoável (art. 48).

## 7. Backup e continuidade

**Situação conferida em 16/11/2026 (Supabase → Database → Backups):**

- Plano **Pro**: backup **físico diário** do banco, por volta de 11h UTC, com os últimos 7 dias disponíveis para restaurar
  (09/11 a 16/11 visíveis). "Restore to new project" disponível.
- **Point in Time Recovery (PITR): não verificado.** Ele é um add-on pago; sem ele, a perda máxima é de até 24 horas.
- **Arquivos do Storage NÃO entram no backup** (aviso do próprio Supabase). A plataforma guarda no Storage as artes
  dos posts (`studio_art`), os arquivos da Biblioteca (`studio_library`) e miniaturas do Instagram (`ig_supabase`).
  Arquivo apagado não volta com a restauração do banco.
- Os buckets dessas artes e arquivos são **públicos** (link `.../object/public/...`): quem tiver o link abre o arquivo.
  O caminho tem identificador aleatório, mas não exige login.
- A organização do Supabase está na conta pessoal **Danilo Portela**, e não numa conta da empresa.

**Pendências:**

1. Cópia externa (fora do Supabase), criptografada, do banco **e dos arquivos do Storage**, com retenção de 30 dias e
   teste de restauração mensal. Destino a escolher (Google Cloud Storage, Cloudflare R2 ou Amazon S3). Nunca guardar
   backup no GitHub (repositório público).
2. Avaliar o PITR, para perder no máximo alguns minutos em vez de até 24 horas.
3. Passar a organização do Supabase para uma conta da AURUM (ou adicionar um segundo dono), para não depender de uma
   pessoa.
4. Avaliar buckets privados com link assinado e de validade curta para materiais do cliente (Biblioteca).

## 8. Pendências para homologação completa

1. Nomear o Encarregado (DPO) e publicar o nome.
2. Definir foro e níveis de serviço nos Termos.
3. Rotina automática de eliminação/anonimização após 90 dias do encerramento.
4. Exportação de dados por empresa (portabilidade).
5. Backup externo criptografado (banco + Storage) e teste de restauração; ver seção 7.
6. Consentimento: banner informativo de armazenamento essencial e registro de consentimento de e-mail/WhatsApp.
