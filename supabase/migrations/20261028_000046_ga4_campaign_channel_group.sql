-- Canal de aquisição do GA4 (sessionDefaultChannelGroup) por campanha.
-- Só uma coluna nova e nula: nenhuma linha muda, nenhuma chave única muda,
-- nenhuma permissão muda (a tabela segue com o RLS e os grants que já tinha).
-- O backend grava sem esta coluna enquanto a migration não for aplicada, e a
-- tela usa um canal derivado de origem/mídia/campanha, marcado como estimado.
alter table public.ga4_campaign_stats add column if not exists channel_group text;

notify pgrst, 'reload schema';
