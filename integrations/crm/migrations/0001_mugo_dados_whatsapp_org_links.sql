-- Run in CRM Supabase ONLY after approval. No existing tables or connections are changed.
-- Map a Mugô Dados tenant to an organization-owned CRM WhatsApp WABA.
-- Do NOT infer a link from a similar company name or a shared CRM organization.
CREATE TABLE IF NOT EXISTS public.mugo_dados_whatsapp_org_links (
  external_client_id text PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS mugo_dados_whatsapp_org_links_org_active_idx
 ON public.mugo_dados_whatsapp_org_links(organization_id) WHERE status='active';
ALTER TABLE public.mugo_dados_whatsapp_org_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mugo_dados_whatsapp_org_links FROM anon,authenticated;
GRANT ALL ON public.mugo_dados_whatsapp_org_links TO service_role;

-- Manual activation for the already-verified Mugô organization, after approval:
-- INSERT INTO public.mugo_dados_whatsapp_org_links
--    (external_client_id, organization_id)
-- VALUES ('388cd0b5-931e-4ff6-8427-aaffec170db7',
--         '1dc27d95-d4c0-447f-a8e8-f0afb6a9f40f')
-- ON CONFLICT (external_client_id)
-- DO UPDATE SET organization_id=excluded.organization_id,
--               status='active',updated_at=now();
