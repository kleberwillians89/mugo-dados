-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; rodar no SQL Editor do Supabase do MUGOVERSO.
-- Lembretes de reunião usam o template aprovado mugo_reuniao_interna, com variáveis nomeadas
-- {{nome}} {{reuniao}} {{data}} {{horario}} {{participantes}}. Vale para equipe e para cliente.
update public.automation_definitions
   set variable_map = '{nome,reuniao,data,horario,participantes}'
 where key = 'reuniao_interna';

update public.automation_definitions
   set template_name = 'mugo_reuniao_interna',
       variable_map = '{nome,reuniao,data,horario,participantes}'
 where key = 'reuniao_lembrete';
