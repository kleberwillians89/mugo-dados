-- Captura universal de leads. Consentimentos declarados NAO autorizam disparos.
-- Aplicacao controlada apos revisar o schema e confirmar o projeto correto.
BEGIN;
CREATE TABLE IF NOT EXISTS public.lead_capture_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  kind text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_-]{1,49}$'),
  token_hash text NOT NULL CHECK (length(token_hash) = 64),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_received_at timestamptz,
  UNIQUE (id, client_id)
);
CREATE INDEX IF NOT EXISTS lead_capture_sources_tenant_idx
  ON public.lead_capture_sources(client_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.lead_capture_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  source_id uuid NOT NULL,
  event_id text NOT NULL CHECK (length(event_id) BETWEEN 1 AND 160),
  email_hash text CHECK (email_hash IS NULL OR length(email_hash) = 64),
  phone_hash text CHECK (phone_hash IS NULL OR length(phone_hash) = 64),
  email_ciphertext text,
  phone_ciphertext text,
  origin_label text CHECK (origin_label IS NULL OR length(origin_label) <= 100),
  consent_email_claimed boolean,
  consent_whatsapp_claimed boolean,
  consent_verified boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'captured' CHECK (status IN ('captured','reviewed','rejected')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id, source_id, event_id),
  FOREIGN KEY (source_id, client_id) REFERENCES public.lead_capture_sources(id, client_id)
);
CREATE INDEX IF NOT EXISTS lead_capture_events_tenant_created_idx
  ON public.lead_capture_events(client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS lead_capture_events_tenant_email_idx
  ON public.lead_capture_events(client_id, email_hash) WHERE email_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS lead_capture_events_tenant_phone_idx
  ON public.lead_capture_events(client_id, phone_hash) WHERE phone_hash IS NOT NULL;

ALTER TABLE public.lead_capture_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lead_capture_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lead_capture_sources, public.lead_capture_events FROM anon, authenticated;
GRANT ALL ON public.lead_capture_sources, public.lead_capture_events TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
