-- Task assignment messages are private to each recipient, not the shared brand chat.
CREATE TABLE IF NOT EXISTS public.studio_task_notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  task_id uuid NOT NULL REFERENCES public.studio_tasks(id) ON DELETE CASCADE,
  recipient_user_id uuid NOT NULL,
  title text NOT NULL CHECK (length(title) <= 200),
  body text NOT NULL CHECK (length(body) <= 2000),
  task_url text NOT NULL CHECK (length(task_url) <= 1000),
  read_at timestamptz,
  whatsapp_status text NOT NULL DEFAULT 'not_configured'
    CHECK (whatsapp_status IN ('not_configured','not_opted_in','pending','sent','failed','skipped_demo')),
  whatsapp_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (client_id,task_id,recipient_user_id)
);
CREATE INDEX IF NOT EXISTS studio_task_notifications_recipient_idx
  ON public.studio_task_notifications(client_id,recipient_user_id,created_at DESC);

-- Consent is deliberately per user and per tenant; it does not imply verified ownership
-- of a phone number. The phone is taken from verified Supabase Auth, never from a task payload.
CREATE TABLE IF NOT EXISTS public.studio_task_whatsapp_preferences (
  client_id text NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  opted_in boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (client_id,user_id)
);
ALTER TABLE public.studio_task_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.studio_task_whatsapp_preferences ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.studio_task_notifications FROM anon,authenticated;
REVOKE ALL ON public.studio_task_whatsapp_preferences FROM anon,authenticated;
GRANT ALL ON public.studio_task_notifications TO service_role;
GRANT ALL ON public.studio_task_whatsapp_preferences TO service_role;
NOTIFY pgrst, 'reload schema';
