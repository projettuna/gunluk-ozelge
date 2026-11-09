-- TMPRO · Yeterlik Sınavı paketi (249 TL / 180 gün). Tekrar çalıştırılabilir.
-- Sorular yalnızca paketi açık üyelere (ve yöneticiye) görünür; soru metinleri bu dosyada DEĞİL,
-- ayrı "sinav_sorular_ekle.sql" dosyasıyla yüklenir (depo herkese açık olduğu için).

alter table public.profiles add column if not exists sinav_until timestamptz;

insert into public.ai_packages (code, ad, adet, gun, fiyat, sira)
values ('SINAV', 'Yeterlik Sınavı Paketi', null, 180, 249, 9)
on conflict (code) do update set ad = excluded.ad, gun = excluded.gun, fiyat = excluded.fiyat;

create or replace function public.has_sinav() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where id = auth.uid()
    and (role = 'admin' or (sinav_until > now() and status = 'active' and (expires_at is null or expires_at > now()))));
$$;
grant execute on function public.has_sinav() to authenticated;

create table if not exists public.sinav_sorular (
  id serial primary key,
  k text not null,                    -- konu (Vergi Usul, KDV ...)
  q text not null,
  o jsonb not null check (jsonb_array_length(o) = 4),
  a int not null check (a between 0 and 3),
  e text not null default '',         -- açıklama ve dayanak
  durum text not null default 'yayinda' check (durum in ('yayinda', 'taslak', 'kapali')),
  kaynak text,                        -- taslak sorularda ilgili mevzuat kaydı
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.sinav_sorular enable row level security;
drop policy if exists "sınav: paket sahibi okur" on public.sinav_sorular;
create policy "sınav: paket sahibi okur" on public.sinav_sorular for select to authenticated
  using ((durum = 'yayinda' and has_sinav()) or is_admin());
drop policy if exists "sınav: yönetici düzenler" on public.sinav_sorular;
create policy "sınav: yönetici düzenler" on public.sinav_sorular for all to authenticated
  using (is_admin()) with check (is_admin());
grant select, insert, update, delete on public.sinav_sorular to authenticated;
grant usage on sequence public.sinav_sorular_id_seq to authenticated;

-- "Bu soru hatalı" bildirimleri
create table if not exists public.sinav_bildirim (
  id bigserial primary key,
  soru_id int not null references public.sinav_sorular(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  nott text not null default '' check (length(nott) <= 600),
  durum text not null default 'acik' check (durum in ('acik', 'kapali')),
  created_at timestamptz not null default now()
);
alter table public.sinav_bildirim enable row level security;
drop policy if exists "bildirim: paket sahibi ekler" on public.sinav_bildirim;
create policy "bildirim: paket sahibi ekler" on public.sinav_bildirim for insert to authenticated
  with check (user_id = auth.uid() and has_sinav());
drop policy if exists "bildirim: yönetici görür" on public.sinav_bildirim;
create policy "bildirim: yönetici görür" on public.sinav_bildirim for select to authenticated using (is_admin() or user_id = auth.uid());
drop policy if exists "bildirim: yönetici kapatır" on public.sinav_bildirim;
create policy "bildirim: yönetici kapatır" on public.sinav_bildirim for update to authenticated using (is_admin()) with check (is_admin());
grant select, insert, update on public.sinav_bildirim to authenticated;
grant usage on sequence public.sinav_bildirim_id_seq to authenticated;

create or replace function public.trg_sinav_bildirim() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from sinav_bildirim where user_id = new.user_id and created_at > now() - interval '1 day') > 20 then
    raise exception 'Günlük bildirim sınırı';
  end if;
  perform notify_admins('Hatalı soru bildirimi', 'Soru #' || new.soru_id || coalesce(': ' || nullif(left(new.nott, 120), ''), ''));
  return new;
end $$;
drop trigger if exists sinav_bildirim_notify on public.sinav_bildirim;
create trigger sinav_bildirim_notify before insert on public.sinav_bildirim for each row execute function public.trg_sinav_bildirim();

-- Yönetici: üyeye sınav paketi aç (gün > 0) / kapat (0)
create or replace function public.set_sinav(uid uuid, days int) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  update profiles set sinav_until = case when days > 0 then greatest(coalesce(sinav_until, now()), now()) + make_interval(days => days) end where id = uid;
end $$;
grant execute on function public.set_sinav(uuid, int) to authenticated;

-- Kredi talebi onayı: SINAV paketi sınav süresini uzatır, diğerleri eskisi gibi
create or replace function public.decide_credit(oid bigint, ok boolean) returns void
language plpgsql security definer set search_path = public as $$
declare o credit_orders; pk ai_packages;
begin
  if not exists (select 1 from profiles where id = auth.uid() and role = 'admin') then raise exception 'yetkisiz'; end if;
  select * into o from credit_orders where id = oid and status = 'pending' for update; if o.id is null then return; end if;
  update credit_orders set status = case when ok then 'approved' else 'rejected' end, decided_at = now() where id = oid;
  if not ok then return; end if;
  select * into pk from ai_packages where code = o.code;
  if pk.code = 'SINAV' then
    update profiles set sinav_until = greatest(coalesce(sinav_until, now()), now()) + make_interval(days => pk.gun) where id = o.user_id;
  elsif pk.gun is not null then
    update profiles set ai_sinirsiz_until = greatest(coalesce(ai_sinirsiz_until, now()), now()) + make_interval(days => pk.gun) where id = o.user_id;
  else
    update profiles set ai_credits = ai_credits + pk.adet where id = o.user_id;
  end if;
end $$;
grant execute on function public.decide_credit(bigint, boolean) to authenticated;

notify pgrst, 'reload schema';
