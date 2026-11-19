-- Roove: quem chega pelo WhatsApp a partir de um anúncio recebe sozinho o convite do grupo do First Access.
update public.whatsapp_ai_settings
set ad_group_link = 'https://chat.whatsapp.com/I3SBELXVK5qCKRZEcgA7Ev',
    ad_group_message = $roove$Que bom ter você por aqui! Entra no grupo do First Access para receber antes de todo mundo as condições da Black Friday Roove e o convite para experimentar o seu primeiro Skinwear: {link}$roove$,
    updated_at = now()
where client_id = 'roove' and (ad_group_link is null or ad_group_link = '');

notify pgrst, 'reload schema';
