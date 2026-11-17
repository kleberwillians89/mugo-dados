-- Campanhas WhatsApp em modo de planejamento. Nenhum mecanismo de envio nesta migration.
BEGIN;
CREATE TABLE IF NOT EXISTS public.whatsapp_campaign_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (char_length(name) BETWEEN 3 AND 120),
  template_name text NOT NULL CHECK (char_length(template_name) BETWEEN 3 AND 81),
  language text NOT NULL CHECK (language IN ('pt_BR', 'en_US', 'es_ES')),
  provider text NOT NULL DEFAULT 'whatsapp',
  audience_source text NOT NULL CHECK (audience_source IN ('relationship_contacts')),
  audience_provider text NOT NULL DEFAULT 'all' CHECK (audience_provider IN ('all', 'shopify', 'fbits', 'whatsapp')),
  status text NOT NULL DEFAULT 'draft' CHECK (status = 'draft'),
  simulated_count integer NOT NULL DEFAULT 0 CHECK (simulated_count >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS whatsapp_campaign_drafts_tenant_created_idx
 ON public.whatsapp_campaign_drafts(client_id, created_at DESC);
ALTER TABLE public.whatsapp_campaign_drafts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_campaign_drafts FROM anon, authenticated;
GRANT ALL ON public.whatsapp_campaign_drafts TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
