alter table public.email_campaigns
  add column internal_review jsonb not null default '{"status":"draft","versions":[]}',
  add column legacy_dispatch boolean not null default false;

-- Preserve only work that had already entered the dispatch queue at rollout.
update public.email_campaigns set legacy_dispatch = true
where status in ('agendada', 'enviando');

alter table public.email_campaigns add constraint email_campaigns_dispatch_needs_approval
  check (status not in ('agendada', 'enviando') or legacy_dispatch
         or coalesce(
           internal_review->>'status' = 'approved'
           and internal_review->'versions'->-1->>'decision' = 'approved'
           and internal_review->'versions'->-1->'snapshot'->'campaign' = jsonb_build_object(
             'name', name, 'subject', subject, 'preheader', preheader, 'custom_html', custom_html,
             'design', design, 'audience', audience
           ), false));

create index email_campaigns_internal_review_idx
  on public.email_campaigns (client_id, updated_at)
  where internal_review->>'status' = 'pending';

notify pgrst, 'reload schema';

create function public.claim_email_campaign(
  p_client_id text, p_campaign_id uuid, p_expected timestamptz,
  p_started timestamptz, p_hashes text[]
) returns setof public.email_campaigns
language plpgsql set search_path = '' as $$
declare
  claimed public.email_campaigns;
begin
  update public.email_campaigns
  set status = 'enviando', started_at = p_started, updated_at = p_started,
      stats = jsonb_build_object('audience', cardinality(p_hashes))
  where client_id = p_client_id and id = p_campaign_id
    and updated_at = p_expected and status = 'agendada'
    and (legacy_dispatch or internal_review->>'status' = 'approved')
  returning * into claimed;
  if not found then return; end if;

  insert into public.email_sends (client_id, kind, campaign_id, email_hash, idem_key)
  select p_client_id, 'campanha', p_campaign_id, hash,
         'campanha/' || p_campaign_id::text || '/' || hash
  from unnest(p_hashes) as recipients(hash)
  on conflict (client_id, idem_key) do nothing;
  return next claimed;
end;
$$;
revoke all on function public.claim_email_campaign(text, uuid, timestamptz, timestamptz, text[]) from public, anon, authenticated;
grant execute on function public.claim_email_campaign(text, uuid, timestamptz, timestamptz, text[]) to service_role;
