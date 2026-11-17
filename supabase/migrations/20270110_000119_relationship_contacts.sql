-- Projeção isolada dos cadastros existentes; não autoriza marketing.
BEGIN;
CREATE TABLE IF NOT EXISTS public.relationship_contacts (
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('shopify', 'fbits')),
  identity_hash text NOT NULL CHECK (length(identity_hash) = 64),
  external_id text,
  email_hash text CHECK (email_hash IS NULL OR length(email_hash) = 32),
  phone_hash text CHECK (phone_hash IS NULL OR length(phone_hash) = 64),
  name_ciphertext text,
  email_ciphertext text,
  phone_ciphertext text,
  marketing_email_verified boolean NOT NULL DEFAULT false,
  marketing_whatsapp_verified boolean NOT NULL DEFAULT false,
  last_synced_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (client_id, provider, identity_hash)
);
CREATE INDEX IF NOT EXISTS relationship_contacts_email_idx ON public.relationship_contacts(client_id, email_hash) WHERE email_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS relationship_contacts_phone_idx ON public.relationship_contacts(client_id, phone_hash) WHERE phone_hash IS NOT NULL;
ALTER TABLE public.relationship_contacts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.relationship_contacts FROM anon, authenticated;
GRANT ALL ON public.relationship_contacts TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
