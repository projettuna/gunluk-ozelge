-- TMPRO · GİB mevzuat arşivi (özelge, tebliğ, sirküler) — Emsal Bul için. Tekrar çalıştırılabilir.
-- Akıştan (items) ayrı tutulur: arşiv kayıtları Son Eklenenler'e, bildirimlere ve takip listesine düşmez.
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

-- Türkçe büyük/küçük harf (İ/I) doğru küçültülür; arama tam metin dizini (simple sözlük) ile
create or replace function public.arsiv_norm(t text) returns text
language sql immutable parallel safe as $$ select lower(translate(coalesce(t, ''), 'İIŞĞÜÖÇ', 'iışğüöç')) $$;
create index if not exists mevzuat_arsiv_fts on public.mevzuat_arsiv
  using gin (to_tsvector('simple', arsiv_norm(title || ' ' || coalesce(metin, ''))));

-- q: to_tsquery ifadesi (ör. 'sahte:* & fatura:*'); en yeni kayıtlar önce.
-- security definer: üyelik bir kez kontrol edilir (satır başına RLS kontrolü zaman aşımına yol açıyordu)
create or replace function public.arsiv_ara(q text, turler text[] default null, lim int default 30)
returns table (tur text, gid bigint, title text, meta text, url text, metin text)
language plpgsql stable security definer set search_path = public as $$
begin
  if not is_active() then raise exception 'yetkisiz'; end if;
  return query
  select a.tur, a.gid, a.title, a.meta, a.url, left(a.metin, 12000)
  from mevzuat_arsiv a
  where to_tsvector('simple', arsiv_norm(a.title || ' ' || coalesce(a.metin, ''))) @@ to_tsquery('simple', arsiv_norm(q))
    and (turler is null or a.tur = any(turler))
  order by a.gid desc
  limit least(greatest(lim, 1), 60);
end $$;
grant execute on function public.arsiv_ara(text, text[], int) to authenticated;

notify pgrst, 'reload schema';
