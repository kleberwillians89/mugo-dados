alter table public.mugo_notice_dismissals
  add column disposition text not null default 'dismissed'
  check (disposition in ('dismissed', 'completed'));

notify pgrst, 'reload schema';
