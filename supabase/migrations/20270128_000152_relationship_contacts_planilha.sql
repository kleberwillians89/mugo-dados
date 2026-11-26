-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- Disparo em massa: leads importados de planilha (Excel ou CSV) entram como origem própria, "planilha",
-- e a campanha pode ir só para os contatos escolhidos.
alter table public.relationship_contacts drop constraint if exists relationship_contacts_provider_check;
alter table public.relationship_contacts add constraint relationship_contacts_provider_check
  check (provider in ('shopify', 'fbits', 'whatsapp', 'planilha'));
alter table public.whatsapp_campaign_drafts drop constraint if exists whatsapp_campaign_drafts_audience_provider_check;
alter table public.whatsapp_campaign_drafts add constraint whatsapp_campaign_drafts_audience_provider_check
  check (audience_provider in ('all', 'shopify', 'fbits', 'whatsapp', 'capture', 'planilha'));
-- Escolha manual de quem recebe (teste com poucos antes de mandar para todos): lista de identity_hash da planilha.
alter table public.whatsapp_campaign_drafts add column if not exists audience_selection jsonb;

-- Reversão:
-- alter table public.whatsapp_campaign_drafts drop column if exists audience_selection;
-- delete from public.relationship_contacts where provider = 'planilha';
-- alter table public.relationship_contacts drop constraint if exists relationship_contacts_provider_check;
-- alter table public.relationship_contacts add constraint relationship_contacts_provider_check check (provider in ('shopify', 'fbits', 'whatsapp'));
-- update public.whatsapp_campaign_drafts set audience_provider = 'all' where audience_provider = 'planilha';
-- alter table public.whatsapp_campaign_drafts drop constraint if exists whatsapp_campaign_drafts_audience_provider_check;
-- alter table public.whatsapp_campaign_drafts add constraint whatsapp_campaign_drafts_audience_provider_check check (audience_provider in ('all', 'shopify', 'fbits', 'whatsapp', 'capture'));
