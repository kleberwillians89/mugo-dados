ALTER TABLE public.whatsapp_campaign_drafts
  DROP CONSTRAINT IF EXISTS whatsapp_campaign_drafts_audience_provider_check;

ALTER TABLE public.whatsapp_campaign_drafts
  ADD CONSTRAINT whatsapp_campaign_drafts_audience_provider_check
  CHECK (audience_provider IN ('all', 'shopify', 'fbits', 'whatsapp', 'capture', 'planilha', 'leads_unificados'));
