begin;

alter table public.whatsapp_campaign_sends add column inbox_message jsonb;
alter table public.whatsapp_threads add column has_campaign boolean not null default false;

create function public.whatsapp_record_campaign_message()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  campaign record;
  thread_id_found uuid;
  sender_id uuid;
  recipient_id text;
  message_text text;
  send_time timestamptz;
begin
  if new.status <> 'sent' or nullif(new.provider_message_id, '') is null or new.phone_key is null then
    return new;
  end if;

  select d.name, d.template_name into campaign
  from public.whatsapp_campaign_drafts d
  where d.id = new.draft_id and d.client_id = new.client_id;
  if not found then return new; end if;

  send_time := coalesce((new.inbox_message->>'sent_at')::timestamptz, new.created_at);
  message_text := coalesce(nullif(new.inbox_message->>'text', ''), 'Campanha enviada: ' || campaign.name);

  if new.inbox_message is not null then
    recipient_id := new.inbox_message->>'wa_id';
    select n.id into sender_id from public.whatsapp_numbers n
    where n.id = (new.inbox_message->>'number_id')::uuid and n.client_id = new.client_id;
    if sender_id is null or recipient_id is null or recipient_id !~ '^[0-9]{6,20}$' then return new; end if;

    insert into public.whatsapp_threads (client_id, number_id, wa_id, phone_key, profile_name, first_seen_at, last_message_at)
    values (new.client_id, sender_id, recipient_id, new.phone_key, nullif(left(new.inbox_message->>'name', 120), ''), send_time, send_time)
    on conflict (number_id, wa_id) do update set wa_id = excluded.wa_id
    returning id into thread_id_found;
  else
    -- O histórico antigo guarda a chave do telefone, mas não o número enviado.
    -- Vincule apenas quando já existe uma conversa inequívoca para essa chave na marca.
    select (array_agg(t.id))[1], (array_agg(t.number_id))[1]
    into thread_id_found, sender_id
    from public.whatsapp_threads t
    where t.client_id = new.client_id and t.phone_key = new.phone_key
    having count(*) = 1;
    if (select count(*) from public.whatsapp_numbers n
        where n.client_id = new.client_id and n.created_at <= send_time) <> 1
       or not exists (select 1 from public.whatsapp_numbers n
                      where n.id = sender_id and n.created_at <= send_time) then
      return new;
    end if;
    if thread_id_found is null then return new; end if;
  end if;

  insert into public.whatsapp_messages (
    client_id, thread_id, number_id, provider_message_id, direction, type, text, status, sent_at, payload
  ) values (
    new.client_id, thread_id_found, sender_id, new.provider_message_id, 'out', 'template',
    left(message_text, 4096), 'sent', send_time,
    jsonb_build_object('campaign_id', new.draft_id, 'template_name', campaign.template_name)
  ) on conflict (number_id, provider_message_id) do nothing;

  update public.whatsapp_threads t set
    has_campaign = true,
    last_preview = case when send_time > t.last_message_at or t.last_preview is null then left(message_text, 140) else t.last_preview end,
    last_direction = case when send_time > t.last_message_at or t.last_preview is null then 'out' else t.last_direction end,
    last_message_at = greatest(t.last_message_at, send_time)
  where t.id = thread_id_found;

  return new;
end;
$$;

revoke all on function public.whatsapp_record_campaign_message() from public, anon, authenticated;
create trigger whatsapp_campaign_send_inbox
after insert or update of status, inbox_message on public.whatsapp_campaign_sends
for each row execute function public.whatsapp_record_campaign_message();

-- Projeta recibos antigos sem executar nenhum envio.
update public.whatsapp_campaign_sends s set inbox_message = null
where s.status = 'sent' and s.inbox_message is null
  and nullif(s.provider_message_id, '') is not null
  and exists (select 1 from public.whatsapp_threads t where t.client_id = s.client_id and t.phone_key = s.phone_key);

notify pgrst, 'reload schema';
commit;
