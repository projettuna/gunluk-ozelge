-- TMPRO · Takvime eklenen günler için 3 gün ve 1 gün önce hatırlatma (gün başına açılıp kapatılabilir). Tekrar çalıştırılabilir.
alter table public.user_events add column if not exists remind boolean not null default true;
notify pgrst, 'reload schema';
