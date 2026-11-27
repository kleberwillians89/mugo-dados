begin;

alter table public.whatsapp_campaign_drafts
  add column if not exists exclude_previous_template_recipients boolean not null default true;

create index if not exists whatsapp_campaign_sends_sent_phone_idx
  on public.whatsapp_campaign_sends (client_id, phone_key)
  where status = 'sent' and phone_key is not null;

notify pgrst, 'reload schema';
commit;
