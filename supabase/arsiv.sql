-- TMPRO · GİB mevzuat arşivi (özelge, tebliğ, sirküler) — Emsal Bul için. Tekrar çalıştırılabilir.
-- Akıştan (items) ayrı tutulur: arşiv kayıtları Son Eklenenler'e, bildirimlere ve takip listesine düşmez.
create extension if not exists pg_trgm;

create table if not exists public.mevzuat_arsiv (
  tur text not null,                 -- Özelge / Tebliğ / Sirküler
  gid bigint not null,               -- GİB kayıt numarası
  title text not null,
  meta text,
  url text,
  metin text,
  updated_at timestamptz not null default now(),
  primary key (tur, gid)
);
alter table public.mevzuat_arsiv enable row level security;
drop policy if exists "arşiv: aktif üyeler okur" on public.mevzuat_arsiv;
create policy "arşiv: aktif üyeler okur" on public.mevzuat_arsiv for select to authenticated using (is_active());
grant select on public.mevzuat_arsiv to authenticated;

create index if not exists mevzuat_arsiv_title_trgm on public.mevzuat_arsiv using gin (title gin_trgm_ops);
create index if not exists mevzuat_arsiv_metin_trgm on public.mevzuat_arsiv using gin (metin gin_trgm_ops);

notify pgrst, 'reload schema';
