-- LOCAL: NÃO APLICADA. Revisão/aplicação remota manual; feature aditiva.
-- Comentários do Instagram: quando a equipe envia uma resposta sugerida pela IA, guarda o texto original da IA.
-- O par (IA sugeriu → equipe enviou) vira sinal do aprendizado da marca, como já acontece no WhatsApp.
alter table public.ig_engagement_actions
  add column if not exists ai_original text check (ai_original is null or length(ai_original) <= 1000);
