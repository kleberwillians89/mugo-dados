-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Avaliação 👍👎 das respostas que a IA mandou sozinha (WhatsApp, Direct, comentários). Toda semana a tela
-- "Aprender com o uso" sorteia algumas para a equipe avaliar; o 👎 com motivo vira sinal do aprendizado da marca.
create table if not exists public.ai_reply_reviews (
  id uuid primary key default gen_random_uuid(),
  client_id text not null references public.clients(id) on delete cascade,
  channel text not null check (channel in ('whatsapp', 'direct', 'comentario')),
  ref_id text not null check (length(ref_id) between 1 and 80),
  customer_text text check (customer_text is null or length(customer_text) <= 600),
  ai_text text not null check (length(ai_text) between 1 and 1000),
  rating text not null check (rating in ('up', 'down')),
  reason text check (reason is null or length(reason) <= 300),
  reviewed_by text,
  created_at timestamptz not null default now(),
  unique (client_id, channel, ref_id)
);
create index if not exists ai_reply_reviews_client_idx on public.ai_reply_reviews (client_id, created_at desc);

alter table public.ai_reply_reviews enable row level security;
revoke all on public.ai_reply_reviews from anon, authenticated;
grant all on public.ai_reply_reviews to service_role;
