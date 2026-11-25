CREATE TABLE public.email_imported_consents (
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  email_hash text NOT NULL,
  email_ciphertext text NOT NULL,
  name_ciphertext text,
  consent boolean NOT NULL,
  source_file text NOT NULL,
  confirmed_by text NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (client_id, email_hash)
);

ALTER TABLE public.email_imported_consents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_imported_consents FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.email_imported_consents TO service_role;
