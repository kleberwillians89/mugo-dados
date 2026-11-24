-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva e retrocompatível.
-- Direcionamento Criativo da peça (Calendário): orientação específica de produção de cada conteúdo.
-- Não substitui o briefing da campanha (studio_briefs) nem a Matriz Tática; fica na própria pauta.
-- Formato: {"concept", "texts", "references", "instructions", "brief_id"} — todos opcionais.
-- Coluna própria (e não signals) para que nenhuma geração da IA sobrescreva o texto da equipe.
-- RLS: herda as políticas já existentes de studio_calendar_items (isolamento por client_id).

alter table public.studio_calendar_items
  add column if not exists creative_direction jsonb not null default '{}'::jsonb;
