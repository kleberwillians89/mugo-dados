-- Contexto de negócio da EMPRESA (não do usuário).
--
-- A Inteligência precisa saber segmento, produto, público, posicionamento,
-- objetivos e observações estratégicas para produzir leitura específica em vez
-- de resumo genérico de métricas. Uma linha por empresa; o conteúdo pertence à
-- empresa e acompanha qualquer usuário com acesso a ela.
--
-- Nada aqui é credencial: é texto editorial escrito pela equipe. Ainda assim o
-- browser não lê esta tabela direto — leitura e escrita passam pelo backend,
-- que já aplica papel e tenant. Fica fechada para anon/authenticated, na mesma
-- linha da migration 038.
--
-- MIGRATION LOCAL — revisar e aplicar remotamente só depois de validada.
-- Idempotente e aditiva: não altera nem apaga nada existente.

create table if not exists public.client_business_context (
  client_id text primary key,
  segment text,
  product_description text,
  audience text,
  positioning text,
  differentiators text,
  commercial_context text,
  goals text,
  strategic_notes text,
  updated_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.client_business_context enable row level security;
revoke all on public.client_business_context from anon, authenticated;
grant all on public.client_business_context to service_role;

drop trigger if exists trg_client_business_context_updated_at on public.client_business_context;
create trigger trg_client_business_context_updated_at
before update on public.client_business_context
for each row execute function public.set_updated_at();

-- Impressão digital do contexto que gerou a análise: permite reusar a análise
-- válida quando os dados relevantes não mudaram, em vez de chamar o modelo a
-- cada visita. Aditiva: linhas antigas ficam com NULL e são simplesmente
-- tratadas como "sem impressão digital".
alter table public.ai_analyses
  add column if not exists context_fingerprint text;

create index if not exists idx_ai_analyses_client_period_fingerprint
  on public.ai_analyses(client_id, period_start, period_end, context_fingerprint);

notify pgrst, 'reload schema';
