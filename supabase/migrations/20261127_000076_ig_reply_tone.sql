-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Tom das respostas de comentários por marca (separado do tom das legendas). Vazio = segue o tom das legendas.
alter table public.ig_engagement_settings
  add column if not exists reply_tone text check (reply_tone is null or length(reply_tone) <= 500);

notify pgrst, 'reload schema';
