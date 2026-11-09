-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Gatilhos de comentários: opção "oi feito pela IA". Quando ligada, a mensagem no Direct é escrita
-- pela IA no tom do perfil da marca; dm_message (opcional) vira o conteúdo que ela precisa levar (link etc.).
alter table public.ig_engagement_rules add column if not exists ai_greeting boolean not null default false;

-- A regra antiga exigia resposta pública ou texto no Direct; agora o oi da IA sozinho também vale.
do $$
declare c record;
begin
  for c in select conname from pg_constraint
           where conrelid = 'public.ig_engagement_rules'::regclass and contype = 'c'
             and pg_get_constraintdef(oid) like '%public_reply IS NOT NULL%dm_message IS NOT NULL%'
  loop
    execute format('alter table public.ig_engagement_rules drop constraint %I', c.conname);
  end loop;
end $$;
alter table public.ig_engagement_rules drop constraint if exists ig_engagement_rules_has_reply;
alter table public.ig_engagement_rules add constraint ig_engagement_rules_has_reply
  check (public_reply is not null or dm_message is not null or ai_greeting);

notify pgrst, 'reload schema';
