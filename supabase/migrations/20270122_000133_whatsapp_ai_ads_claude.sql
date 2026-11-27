-- Atendente de IA do WhatsApp: (1) quem chega por anúncio recebe o link do grupo; (2) chave do Claude da própria marca.
alter table public.whatsapp_ai_settings
  add column if not exists ad_group_link text check (ad_group_link is null or (ad_group_link ~ '^https://' and length(ad_group_link) <= 500)),
  add column if not exists ad_group_message text not null default '' check (length(ad_group_message) <= 1000),
  add column if not exists claude_api_key_encrypted text,
  add column if not exists claude_key_hint text check (claude_key_hint is null or length(claude_key_hint) <= 12),
  add column if not exists claude_model text not null default 'claude-sonnet-5-5'
    check (claude_model in ('claude-haiku-5-5', 'claude-sonnet-5-5', 'claude-opus-5-5'));

-- Quando o link do grupo foi enviado nesta conversa (uma vez só).
alter table public.whatsapp_threads add column if not exists ai_group_sent_at timestamptz;
