-- Disparo em massa de WhatsApp: a campanha sai do rascunho e é enviada (template aprovado pela Meta).
-- Cada destinatário fica registrado uma vez por campanha (retomar não reenvia para quem já recebeu).
BEGIN;
ALTER TABLE public.whatsapp_campaign_drafts DROP CONSTRAINT IF EXISTS whatsapp_campaign_drafts_status_check;
ALTER TABLE public.whatsapp_campaign_drafts ADD CONSTRAINT whatsapp_campaign_drafts_status_check
  CHECK (status IN ('draft', 'sending', 'sent', 'partial', 'failed'));
ALTER TABLE public.whatsapp_campaign_drafts DROP CONSTRAINT IF EXISTS whatsapp_campaign_drafts_audience_source_check;
ALTER TABLE public.whatsapp_campaign_drafts ADD CONSTRAINT whatsapp_campaign_drafts_audience_source_check
  CHECK (audience_source IN ('relationship_contacts', 'lead_capture_events'));
ALTER TABLE public.whatsapp_campaign_drafts DROP CONSTRAINT IF EXISTS whatsapp_campaign_drafts_audience_provider_check;
ALTER TABLE public.whatsapp_campaign_drafts ADD CONSTRAINT whatsapp_campaign_drafts_audience_provider_check
  CHECK (audience_provider IN ('all', 'shopify', 'fbits', 'whatsapp', 'capture'));
ALTER TABLE public.whatsapp_campaign_drafts
  ADD COLUMN IF NOT EXISTS sent_count integer NOT NULL DEFAULT 0 CHECK (sent_count >= 0),
  ADD COLUMN IF NOT EXISTS failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
  ADD COLUMN IF NOT EXISTS skipped_count integer NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
  ADD COLUMN IF NOT EXISTS recipients_count integer NOT NULL DEFAULT 0 CHECK (recipients_count >= 0),
  ADD COLUMN IF NOT EXISTS started_at timestamptz,
  ADD COLUMN IF NOT EXISTS finished_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_error text CHECK (last_error IS NULL OR length(last_error) <= 300);

CREATE TABLE IF NOT EXISTS public.whatsapp_campaign_sends (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  draft_id uuid NOT NULL REFERENCES public.whatsapp_campaign_drafts(id) ON DELETE CASCADE,
  phone_hash text NOT NULL CHECK (length(phone_hash) = 64),
  status text NOT NULL CHECK (status IN ('sent', 'failed', 'skipped')),
  error text CHECK (error IS NULL OR length(error) <= 300),
  provider_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (draft_id, phone_hash)
);
CREATE INDEX IF NOT EXISTS whatsapp_campaign_sends_draft_idx ON public.whatsapp_campaign_sends(draft_id, status);
ALTER TABLE public.whatsapp_campaign_sends ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_campaign_sends FROM anon, authenticated;
GRANT ALL ON public.whatsapp_campaign_sends TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
