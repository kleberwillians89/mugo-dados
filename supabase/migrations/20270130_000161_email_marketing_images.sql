insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('email-marketing-images', 'email-marketing-images', true, 5242880, array['image/jpeg', 'image/png'])
on conflict (id) do nothing;

create policy email_marketing_images_no_direct_insert on storage.objects
as restrictive for insert to anon, authenticated
with check (bucket_id <> 'email-marketing-images');

create policy email_marketing_images_no_direct_update on storage.objects
as restrictive for update to anon, authenticated
using (bucket_id <> 'email-marketing-images')
with check (bucket_id <> 'email-marketing-images');

create policy email_marketing_images_no_direct_delete on storage.objects
as restrictive for delete to anon, authenticated
using (bucket_id <> 'email-marketing-images');
