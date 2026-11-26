-- Roove First Access: attribution, encrypted name, consent evidence.
-- Apply ONLY in approved isolated environment after schema review. No data migration.
BEGIN;
ALTER TABLE public.lead_capture_events
  ADD COLUMN IF NOT EXISTS name_ciphertext text,
  ADD COLUMN IF NOT EXISTS campaign_key text,
  ADD COLUMN IF NOT EXISTS utm_source text,
  ADD COLUMN IF NOT EXISTS utm_medium text,
  ADD COLUMN IF NOT EXISTS utm_campaign text,
  ADD COLUMN IF NOT EXISTS consent_version text;
CREATE INDEX IF NOT EXISTS lead_capture_campaign_idx
  ON public.lead_capture_events(client_id, campaign_key, created_at DESC);
COMMIT;
NOTIFY pgrst, 'reload schema';
