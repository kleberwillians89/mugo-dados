-- Atendente de IA: como as peças aparecem na conversa (carrossel com foto e botão, catálogo da Meta ou links).
alter table public.whatsapp_ai_settings
  add column if not exists product_style text not null default 'carrossel' check (product_style in ('carrossel', 'catalogo', 'links')),
  add column if not exists product_button text not null default 'Garantir meu look' check (length(product_button) between 1 and 20);

notify pgrst, 'reload schema';
