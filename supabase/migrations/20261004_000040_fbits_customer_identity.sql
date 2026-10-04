-- Customer 360 FBITS: identidade do cliente em tabela própria.
--
-- NÃO APLICADA. Criada nesta rodada e deixada pendente de propósito.
--
-- POR QUE UMA TABELA SEPARADA
-- `fbits_orders` guarda só o necessário para analytics mais o `customer_id`, e
-- `sanitize_order_raw` reduz o objeto `usuario` do pedido a `usuarioId` e
-- `tipoPessoa`. Essa decisão é protegida por teste
-- (test_fbits_multitenant.test_pii_is_never_persisted) e NÃO é revertida: o
-- pedido continua sem PII. A identidade do cliente passa a viver aqui, com
-- finalidade declarada e ciclo de vida próprio.
--
-- ACESSO
-- Tabela de PII nasce fechada, no mesmo padrão das migrations 038 e 039: RLS
-- ligado, nada para anon/authenticated, tudo para service_role. Não existe
-- policy para o browser de propósito — o acesso é exclusivamente pelo backend,
-- que já resolve membership e tenant antes de qualquer leitura. Sem isto, uma
-- tabela nova em `public` seria lida pela anon key de qualquer tenant, que é
-- exatamente o que a 038 teve de corrigir em meta_oauth_handoffs e
-- shopify_refunds.
--
-- MINIMIZAÇÃO
-- GET /pedidos devolve, por pedido, `usuario` com usuarioId, tipoPessoa, nome,
-- email, telefoneCelular e cpf. Persistimos apenas o que o Customer 360 usa:
-- nome, e-mail e telefone. CPF, endereço e meio de pagamento continuam
-- descartados na leitura e não têm coluna aqui — não é esquecimento, é
-- minimização: coluna que não existe não pode ser preenchida por engano.

create table if not exists public.fbits_customers (
  id uuid primary key default gen_random_uuid(),
  client_id text not null,
  fbits_customer_id text not null,
  name text,
  email text,
  phone text,
  created_at_provider timestamptz,
  updated_at_provider timestamptz,
  synced_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_id, fbits_customer_id)
);

-- ---------------------------------------------------------------------------
-- Fechamento de acesso. Vem logo após o create table de propósito: a tabela
-- não fica aberta nem entre duas instruções da mesma migration.
-- ---------------------------------------------------------------------------
alter table public.fbits_customers enable row level security;
revoke all on public.fbits_customers from anon, authenticated;
grant all on public.fbits_customers to service_role;

-- Nenhuma policy é criada. Com RLS ligado e sem policy, nenhum papel sujeito a
-- RLS lê a tabela; o backend usa service_role, que tem BYPASSRLS. É mais
-- restritivo que uma policy por tenant e não duplica no banco a regra de
-- membership que já vive em require_client_read.

-- Isolamento por tenant em todo acesso: o índice composto começa sempre por
-- client_id, nunca pelo id externo sozinho.
create index if not exists idx_fbits_customers_client
  on public.fbits_customers (client_id);

-- Enriquecimento da listagem: busca o lote de clientes do tenant.
create index if not exists idx_fbits_customers_client_customer
  on public.fbits_customers (client_id, fbits_customer_id);

-- Sync incremental: quem foi visto mais recentemente.
create index if not exists idx_fbits_customers_client_synced
  on public.fbits_customers (client_id, synced_at desc);

comment on table public.fbits_customers is
  'Identidade do cliente FBITS para o Customer 360. Finalidade: exibir a base '
  'de clientes da própria empresa ao próprio tenant. Contém dado pessoal '
  '(nome, e-mail, telefone). Não contém CPF, endereço nem meio de pagamento.';

-- ---------------------------------------------------------------------------
-- Exclusão permanente, amarrada ao ciclo de vida da empresa.
--
-- `delete_platform_company` (migration 036) termina com
-- `delete from public.clients where id = p_client_id`. Um trigger nessa
-- exclusão apaga a identidade dos clientes automaticamente, por QUALQUER
-- caminho que remova a empresa — não só por aquela função. Preferido a
-- reescrever as ~130 linhas do corpo de 036, que duplicaria código e abriria
-- espaço para as duas versões divergirem em silêncio.
--
-- Atende o direito de eliminação da LGPD (art. 18, VI): sem isto, apagar a
-- empresa deixaria dado pessoal de cliente para trás.
-- ---------------------------------------------------------------------------
create or replace function public.purge_fbits_customers_for_client()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  delete from public.fbits_customers where client_id = old.id;
  return old;
end;
$$;

drop trigger if exists trg_purge_fbits_customers on public.clients;
create trigger trg_purge_fbits_customers
  after delete on public.clients
  for each row
  execute function public.purge_fbits_customers_for_client();

-- Exclusão pontual de um cliente (pedido do titular do dado, sem apagar a
-- empresa). A identidade sai; o pedido permanece, porque já é anônimo — só
-- tem o id externo, que deixa de resolver para uma pessoa.
create or replace function public.forget_fbits_customer(
  p_client_id text,
  p_fbits_customer_id text
)
returns bigint
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_deleted bigint := 0;
begin
  delete from public.fbits_customers
   where client_id = p_client_id
     and fbits_customer_id = p_fbits_customer_id;
  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

-- RPC destrutiva: fechada para o browser. `revoke from public` sozinho não
-- basta, porque o default privilege do Supabase concede execute a anon e
-- authenticated explicitamente — foi assim que a 038 fechou
-- acquire_client_job_lock / release_client_job_lock.
revoke all on function public.forget_fbits_customer(text, text)
  from public, anon, authenticated;
grant execute on function public.forget_fbits_customer(text, text)
  to service_role;

-- A função do trigger também sai do alcance do browser. Isto NÃO quebra o
-- trigger: o PostgreSQL verifica EXECUTE na função do trigger no momento do
-- CREATE TRIGGER, não a cada disparo. O trigger segue rodando internamente.
revoke all on function public.purge_fbits_customers_for_client()
  from public, anon, authenticated;
grant execute on function public.purge_fbits_customers_for_client()
  to service_role;

-- PostgREST precisa recarregar o schema para enxergar a tabela nova; sem isto
-- o backend receberia PGRST205. Mesmo final das migrations 038 e 039.
notify pgrst, 'reload schema';
