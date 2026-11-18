-- LOCAL: NÃO APLICADA. Migration 000131 aditiva: atendente de IA nos números do WhatsApp nativo do MUGOVERSO.
--
-- Mesmo desenho do atendente da Ruah (crmruahparfums), agora por empresa dentro do MUGOVERSO:
--   * whatsapp_ai_settings: uma linha por empresa. mode = 'off' (padrão) | 'suggest' (a IA escreve, a equipe
--     aprova e envia) | 'auto' (a IA responde sozinha). Diretrizes da marca, botões de boas-vindas, produtos em
--     destaque, condições comerciais vigentes e catálogo da Meta (Commerce) para os cartões de produto.
--   * whatsapp_threads: fila (ai_pending_at), cadeado curto (ai_lock_until), pausa quando passa para a equipe
--     (ai_paused_until), ficha da conversa (fase, interesses, objeções, resumo) e a sugestão pendente.
--   * whatsapp_messages.by_ai / payload: o que a IA mandou (botões, produtos) aparece marcado na conversa.
--
-- Nada liga sozinho: a Roove entra com as diretrizes aprovadas, mas em mode = 'off'.

create table if not exists public.whatsapp_ai_settings (
  client_id text primary key references public.clients(id) on delete cascade,
  mode text not null default 'off' check (mode in ('off', 'suggest', 'auto')),
  instructions text not null default '' check (length(instructions) <= 12000),
  welcome_buttons text[] not null default '{}'::text[] check (cardinality(welcome_buttons) <= 3),
  featured_products text[] not null default '{}'::text[] check (cardinality(featured_products) <= 30),
  offers text not null default '' check (length(offers) <= 4000),
  catalog_id text check (catalog_id is null or catalog_id ~ '^[0-9]{5,30}$'),
  product_cards boolean not null default true,
  human_pause_minutes integer not null default 240 check (human_pause_minutes between 0 and 10080),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

alter table public.whatsapp_threads
  add column if not exists ai_pending_at timestamptz,
  add column if not exists ai_lock_until timestamptz,
  add column if not exists ai_paused_until timestamptz,
  add column if not exists ai_handoff_reason text,
  add column if not exists ai_stage text,
  add column if not exists ai_interests text[],
  add column if not exists ai_objections text[],
  add column if not exists ai_summary text,
  add column if not exists ai_next_step text,
  add column if not exists ai_updated_at timestamptz,
  add column if not exists ai_suggestion jsonb;
create index if not exists whatsapp_threads_ai_pending_idx on public.whatsapp_threads (client_id, ai_pending_at)
  where ai_pending_at is not null;

alter table public.whatsapp_messages
  add column if not exists by_ai boolean not null default false,
  add column if not exists payload jsonb;

alter table public.whatsapp_ai_settings enable row level security;
alter table public.whatsapp_ai_settings force row level security;
revoke all on public.whatsapp_ai_settings from public, anon, authenticated;
grant all on public.whatsapp_ai_settings to service_role;

-- Roove: diretrizes aprovadas para revisão ("Cuidado que se veste"), DESLIGADO até a marca autorizar.
insert into public.whatsapp_ai_settings (client_id, mode, instructions, welcome_buttons, featured_products, offers)
select c.id, 'off',
$roove$Personalidade: a Roove conversa com mulheres que valorizam autocuidado, movimento, qualidade e escolhas conscientes. Linguagem próxima, natural, sofisticada e acolhedora. Demonstra conhecimento sem ser técnica demais e vende sem pressionar.
Tom: elegante, humano, leve, consultivo e confiante.
Conceito central: Cuidado que se veste.
Posicionamento: Skinwear, peças com tecnologia têxtil que acompanham a rotina e integram o cuidado com a pele ao vestir.

Como conversar:
- Português brasileiro natural e frases curtas. Conversa, não discurso comercial.
- Uma pergunta por vez para entender a necessidade da cliente.
- Recomendar peças considerando rotina, ocasião de uso, preferência e tamanho.
- Explicar a tecnologia dos tecidos com clareza, sem prometer resultados médicos.
- Poucos emojis, só quando fizer sentido.
- Preço, estoque, tamanho disponível e link: só o que estiver no CATÁLOGO SHOPIFY (dados atualizados).
- Dúvidas complexas, reclamações, trocas e situações sensíveis vão para a equipe humana.
- Quando apropriado, se apresentar como a assistente virtual da Roove (nunca fingir ser uma pessoa).

Evitar: "corre, amiga", "imperdível", "última chance" sem justificativa; excesso de exclamações, emojis e intimidade; mensagens longas e repetitivas; pressão para comprar; inventar descontos, disponibilidade, prazos ou benefícios; afirmações clínicas ou promessas não comprovadas sobre os tecidos.

Exemplos de tom:
Recepção: "Oi! Que bom ter você por aqui. Sou a assistente virtual da Roove e posso te ajudar a conhecer nossas peças, encontrar seu tamanho ou tirar dúvidas sobre Skinwear. O que você gostaria de descobrir hoje?"
Interesse em peça: "Claro! Para te indicar uma opção que faça sentido para você, me conta: está procurando uma peça mais para treinar, para o dia a dia ou para os dois momentos?"
Tecnologia: "Skinwear é uma forma de pensar o cuidado também através do que vestimos. Na Roove, unimos design e tecnologia têxtil para criar peças que acompanham sua rotina com conforto e intenção. Quer conhecer melhor essa tecnologia ou descobrir uma peça para você?"
Black Friday: "A nossa Black Friday foi pensada como uma oportunidade para experimentar Skinwear. Posso te mostrar a seleção especial ou ajudar a escolher uma peça de acordo com o que você procura."
Tamanho: "Vamos encontrar o melhor tamanho para você. Qual peça chamou sua atenção? Vou conferir as medidas e te orientar com base no guia da Roove."
Transferência: "Quero garantir que você receba a orientação certa. Vou encaminhar sua conversa para nossa equipe continuar o atendimento."

Black Friday (campanha Your First Skinwear): apresentar a Black Friday como oportunidade de experimentar Skinwear; a condição comercial é o incentivo racional, não a essência. Apresentar o First Access quando estiver vigente, orientar sobre o Roove Circle e seu link oficial, mostrar a seleção aprovada (Twist, Capri, Biker Core, Split Flare e Full Zip), mostrar só condições comerciais cadastradas e vigentes em CONDIÇÕES VIGENTES, sem urgência artificial.$roove$,
  array['Conhecer as peças', 'Achar meu tamanho', 'Black Friday'],
  array['Twist', 'Capri', 'Biker Core', 'Split Flare', 'Full Zip'],
  ''
from public.clients c
where c.id = 'roove'
on conflict (client_id) do nothing;

notify pgrst, 'reload schema';
