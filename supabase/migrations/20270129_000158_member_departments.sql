-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva (reversão no fim do arquivo).
-- Departamentos de cada profissional (Design, Social Media…): na Nova tarefa, escolher a área mostra primeiro quem é dela.
-- Por pessoa (vale em todos os clientes); uma pessoa pode ter várias áreas. Editado em Configurações → Usuários.
create table if not exists public.member_departments (
  user_id uuid not null,
  department text not null check (char_length(department) between 1 and 60),
  updated_by uuid,
  updated_at timestamptz not null default now(),
  primary key (user_id, department)
);
alter table public.member_departments enable row level security;
revoke all on public.member_departments from anon, authenticated;
grant all on public.member_departments to service_role;
notify pgrst, 'reload schema';

-- Reversão:
-- drop table if exists public.member_departments;
