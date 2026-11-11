-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Esteira em duas fases e Matriz com período variável:
-- * a esteira para na Matriz ("aguardando") para a equipe conferir e só segue no "Gerar conteúdo";
-- * pedidos que chegam com a esteira ocupada entram na fila ("na_fila") e rodam na ordem;
-- * options guarda o período (semanas, início), o foco/briefing e o briefing de origem;
-- * a Matriz guarda quantas semanas tem (1 a 8; antes eram sempre 4);
-- * a conversa da aba Mugô IA fica no mesmo histórico do agente da marca, separada pelo canal (meta.channel = 'mugo_ia'; só um índice novo).

alter table public.studio_agent_runs drop constraint if exists studio_agent_runs_status_check;
alter table public.studio_agent_runs add constraint studio_agent_runs_status_check
  check (status in ('na_fila', 'rodando', 'aguardando', 'concluida', 'falhou', 'cancelada'));
alter table public.studio_agent_runs add column if not exists options jsonb not null default '{}'::jsonb
  check (jsonb_typeof(options) = 'object');

alter table public.studio_content_matrices add column if not exists weeks smallint not null default 4
  check (weeks between 1 and 8);

create index if not exists brand_agent_messages_channel_idx
  on public.brand_agent_messages (client_id, user_id, (meta->>'channel'), created_at desc);

notify pgrst, 'reload schema';
