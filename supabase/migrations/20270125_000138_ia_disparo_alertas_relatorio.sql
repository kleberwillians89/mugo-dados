-- Melhorias de 20/11/2026:
-- 1) disparo em massa: fila/agendamento (roda no Relógio dos jobs, não no Render), modelo com imagem no topo
--    e relatório depois do envio (responderam/compraram pela phone_key, a mesma chave do resto do WhatsApp);
-- 2) aprendizados da marca: o que cada post e anúncio rendeu comparado com a média (a IA lê);
-- 3) alertas da Mídia On (avisos no Chat de tarefas, sem repetir no mesmo dia);
-- 4) relatório mensal: fechado no dia 1º como rascunho, liberado pela equipe, com link para quem não tem login.
BEGIN;

ALTER TABLE public.whatsapp_campaign_drafts DROP CONSTRAINT IF EXISTS whatsapp_campaign_drafts_status_check;
ALTER TABLE public.whatsapp_campaign_drafts ADD CONSTRAINT whatsapp_campaign_drafts_status_check
  CHECK (status IN ('draft', 'queued', 'sending', 'sent', 'partial', 'failed'));
ALTER TABLE public.whatsapp_campaign_drafts
  ADD COLUMN IF NOT EXISTS scheduled_at timestamptz,
  ADD COLUMN IF NOT EXISTS header_media_url text CHECK (header_media_url IS NULL OR (header_media_url ~ '^https://' AND length(header_media_url) <= 1000));
ALTER TABLE public.whatsapp_campaign_sends
  ADD COLUMN IF NOT EXISTS phone_key text CHECK (phone_key IS NULL OR phone_key ~ '^[0-9a-f]{32}$');
CREATE INDEX IF NOT EXISTS whatsapp_campaign_drafts_queue_idx ON public.whatsapp_campaign_drafts(status, scheduled_at)
  WHERE status IN ('queued', 'sending');

CREATE TABLE IF NOT EXISTS public.brand_learnings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('post', 'ad')),
  ref_id text NOT NULL CHECK (length(ref_id) BETWEEN 1 AND 80),
  verdict text NOT NULL CHECK (verdict IN ('acima', 'na_media', 'abaixo')),
  lesson text NOT NULL CHECK (length(lesson) BETWEEN 1 AND 600),
  facts jsonb NOT NULL DEFAULT '{}'::jsonb,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id, kind, ref_id)
);
CREATE INDEX IF NOT EXISTS brand_learnings_client_idx ON public.brand_learnings(client_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.media_alerts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  ref_id text NOT NULL CHECK (length(ref_id) BETWEEN 1 AND 80),
  kind text NOT NULL CHECK (kind IN ('reprovada', 'com_problema', 'custo_alto', 'sem_entrega', 'fim_proximo')),
  message text NOT NULL CHECK (length(message) BETWEEN 1 AND 500),
  day date NOT NULL DEFAULT (now() AT TIME ZONE 'America/Sao_Paulo')::date,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id, ref_id, kind, day)
);
CREATE INDEX IF NOT EXISTS media_alerts_client_idx ON public.media_alerts(client_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.monthly_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
  status text NOT NULL DEFAULT 'rascunho' CHECK (status IN ('rascunho', 'liberado')),
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  summary text CHECK (summary IS NULL OR length(summary) <= 4000),
  share_token text UNIQUE CHECK (share_token IS NULL OR length(share_token) BETWEEN 24 AND 80),
  released_at timestamptz,
  released_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id, month)
);

ALTER TABLE public.brand_learnings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.media_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.monthly_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.brand_learnings, public.media_alerts, public.monthly_reports FROM anon, authenticated;
GRANT ALL ON public.brand_learnings, public.media_alerts, public.monthly_reports TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
