# Mugô Studio — arte na pauta (armazenamento)

> A página Biblioteca saiu do menu. O armazenamento continua: é ele que guarda a arte das pautas
> (enviada pelo modal da pauta) e o guia da marca em PDF (enviado no Brand Manager).

## Como o arquivo chega ao Storage

O arquivo **nunca passa pelo Render** (512 MB de RAM, corta requisição longa).

1. `POST /api/clients/{id}/studio/assets/upload-url` — o backend confere o papel
   (`agency_admin`/`client_admin`), o tipo e o tamanho, grava `studio_assets` como
   `pendente` e devolve uma URL assinada de upload para `{client_id}/{uuid}.{ext}`
   (e outra para a miniatura `{uuid}.thumb.jpg`, quando o navegador conseguiu gerá-la).
2. O navegador faz `PUT` direto nessa URL, mostrando o progresso.
3. `POST .../assets/{id}/confirm` — o backend lê o objeto real no Storage (existe,
   tamanho, tipo gravado e assinatura dos primeiros bytes). Só então marca `pronto`.
   Arquivo que não corresponde ao tipo declarado ou que passa do limite é apagado.

Uploads que nunca foram confirmados são apagados depois de 24 h pelo job
`studio-assets-cleanup` (GitHub Actions, todo dia às 04:50 UTC).

| Tipo | Formatos | Limite |
|---|---|---|
| Imagem | JPG, PNG, WEBP | 15 MB |
| Vídeo | MP4, MOV | 200 MB |
| PDF | PDF | 30 MB |

O bucket `studio-assets` é **privado** e também aplica o teto de 200 MB e a lista de
tipos. Não há policy em `storage.objects`: só o backend (service role) acessa.
A leitura é sempre por URL assinada de 1 h, gerada a cada listagem.

## Arte na pauta

- Uma pauta aceita de 1 a 20 imagens/vídeos (`studio_calendar_item_assets`); a
  `position` é a ordem dos slides do carrossel. PDFs ficam só na Biblioteca.
- `PUT .../calendar/items/{item_id}/assets` com `{"asset_ids": [...]}` troca a lista inteira.
- O calendário (`GET .../calendar`) e a página pública `/aprovar/<token>` recebem
  `assets` com URLs assinadas. A página pública recebe só o tipo, as dimensões e as URLs
  (sem nome, pasta, tags nem caminho).
- Excluir um arquivo da Biblioteca tira esse arquivo de todas as pautas.

## Para ligar em produção (Kleber)

1. Aplicar `supabase/migrations/20261103_000052_studio_assets.sql` no SQL Editor
   (ele cria o bucket e as duas tabelas).
2. Em **Storage → Settings**, subir o limite global de upload para **pelo menos 200 MB**
   (o padrão do projeto pode ser 50 MB; acima dele o Storage recusa o vídeo).
3. Variável opcional `STUDIO_ASSETS_BUCKET` (padrão `studio-assets`) no Render e no
   segredo `MUGO_JOBS_ENV`. Nenhuma chave nova é necessária.

## Limites conhecidos

- O envio é simples (um `PUT`). Se Reels grandes falharem no celular em rede ruim,
  o próximo passo é o upload resumível (TUS) do Supabase.
- A miniatura é gerada no navegador. Vídeos que o navegador não decodifica (ex.: HEVC no
  Chrome do Windows) sobem sem miniatura, mas tocam normalmente onde o formato é suportado.
- Ao excluir uma empresa, as linhas somem em cascata, mas os arquivos do bucket ficam
  na pasta `{client_id}/` (limpeza manual no painel do Storage).
