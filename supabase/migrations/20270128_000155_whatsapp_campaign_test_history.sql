begin;

create function public.whatsapp_record_campaign_test(
  p_client_id text, p_number_id uuid, p_wa_id text, p_phone_key text,
  p_provider_message_id text, p_text text, p_template_name text, p_sent_at timestamptz
) returns void language plpgsql set search_path = '' as $$
declare
  v_thread_id uuid;
begin
  if not exists (select 1 from public.whatsapp_numbers n where n.id = p_number_id and n.client_id = p_client_id) then
    raise exception 'Número não pertence à marca';
  end if;

  insert into public.whatsapp_threads as t (client_id, number_id, wa_id, phone_key, first_seen_at, last_message_at)
  values (p_client_id, p_number_id, p_wa_id, p_phone_key, p_sent_at, p_sent_at)
  on conflict (number_id, wa_id) do update set wa_id = excluded.wa_id
    where t.client_id = excluded.client_id
  returning id into v_thread_id;

  insert into public.whatsapp_messages (
    client_id, thread_id, number_id, provider_message_id, direction, type, text, status, sent_at, payload
  ) values (
    p_client_id, v_thread_id, p_number_id, p_provider_message_id, 'out', 'template',
    left(p_text, 4096), 'sent', p_sent_at,
    jsonb_build_object('campaign_test', true, 'template_name', p_template_name)
  ) on conflict (number_id, provider_message_id) do nothing;

  update public.whatsapp_threads t set
    has_campaign = true,
    last_preview = case when p_sent_at > t.last_message_at or t.last_preview is null then left(p_text, 140) else t.last_preview end,
    last_direction = case when p_sent_at > t.last_message_at or t.last_preview is null then 'out' else t.last_direction end,
    last_message_at = greatest(t.last_message_at, p_sent_at)
  where t.id = v_thread_id;
end;
$$;

revoke all on function public.whatsapp_record_campaign_test(text, uuid, text, text, text, text, text, timestamptz)
  from public, anon, authenticated;
grant execute on function public.whatsapp_record_campaign_test(text, uuid, text, text, text, text, text, timestamptz)
  to service_role;

notify pgrst, 'reload schema';
commit;
