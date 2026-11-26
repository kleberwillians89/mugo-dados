-- Registro de app Meta por numero: preserva o app legado quando NULL.
-- A propriedade do numero continua presa ao client_id, conforme migration 000087.
alter table public.whatsapp_numbers
  add column if not exists meta_app_id text;
alter table public.whatsapp_numbers
  drop constraint if exists whatsapp_numbers_meta_app_id_valid;
alter table public.whatsapp_numbers
  add constraint whatsapp_numbers_meta_app_id_valid
  check (meta_app_id is null or meta_app_id ~ '^[0-9]{5,30}$');

comment on column public.whatsapp_numbers.meta_app_id is
  'Meta App ID do webhook de entrada; NULL usa o app legado WHATSAPP_APP_SECRET.';
notify pgrst, 'reload schema';
