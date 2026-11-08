-- TMPRO: Abonelik 149 TL (30 asistan sorusu dahil) + IBAN ile alınan kredi paketleri
insert into public.settings (key, value) values ('ai_kota', '30') on conflict (key) do nothing;
update public.settings set value = '149' where key = 'fiyat';

alter table public.profiles add column if not exists ai_unlimited boolean not null default false;   -- yönetici verir (ör. Merve)
alter table public.profiles add column if not exists ai_credits int not null default 0;             -- satın alınan ek soru
alter table public.profiles add column if not exists ai_sinirsiz_until timestamptz;                 -- sınırsız paket bitişi
update public.profiles set ai_unlimited = true where status = 'active' and expires_at is null;      -- süresiz üyeler

-- Paketler (fiyatları yönetici buradan değiştirebilir)
create table if not exists public.ai_packages (
  code text primary key, ad text not null, adet int, gun int, fiyat int not null, sira int not null default 0
);
insert into public.ai_packages (code, ad, adet, gun, fiyat, sira) values
  ('K20',  '20 Soru',  20,  null, 79,  1),
  ('K50',  '50 Soru',  50,  null, 179, 2),
  ('K120', '120 Soru', 120, null, 379, 3),
  ('SINIRSIZ', 'Aylık Sınırsız', null, 30, 699, 4)
on conflict (code) do nothing;
alter table public.ai_packages enable row level security;
drop policy if exists "paketler: herkes okur" on public.ai_packages;
create policy "paketler: herkes okur" on public.ai_packages for select using (true);
grant select on public.ai_packages to anon, authenticated;

-- Kredi talepleri
create table if not exists public.credit_orders (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  code text not null references public.ai_packages(code),
  fiyat int not null,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  decided_at timestamptz
);
alter table public.credit_orders enable row level security;
drop policy if exists "kredi: kendini görür" on public.credit_orders;
create policy "kredi: kendini görür" on public.credit_orders for select
  using (user_id = auth.uid() or exists (select 1 from profiles where id = auth.uid() and role = 'admin'));
grant select on public.credit_orders to authenticated;

create table if not exists public.ai_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  ay text not null,
  n int not null default 0,
  primary key (user_id, ay)
);
alter table public.ai_usage enable row level security;
drop policy if exists "kota: kendini görür" on public.ai_usage;
create policy "kota: kendini görür" on public.ai_usage for select using (user_id = auth.uid());
grant select on public.ai_usage to authenticated;

-- Bu ayki kullanım, aylık sınır (null = sınırsız), kalan kredi, sınırsız paket bitişi
create or replace function public.ai_quota() returns json
language sql security definer set search_path = public stable as $$
  select json_build_object(
    'used', coalesce((select n from ai_usage where user_id = p.id and ay = to_char(now() at time zone 'Europe/Istanbul', 'YYYY-MM')), 0),
    'limit', case when p.role = 'admin' or p.ai_unlimited then null
                  when p.ai_sinirsiz_until > now() then 200        -- sınırsız pakette adil kullanım
                  else coalesce((select value::int from settings where key = 'ai_kota'), 30) end,
    'credits', p.ai_credits,
    'sinirsiz_until', p.ai_sinirsiz_until)
  from profiles p where p.id = auth.uid();
$$;

-- Bir soru düşer: önce aylık hak, bitince kredi. Hak yoksa false.
create or replace function public.use_ai_quota() returns boolean
language plpgsql security definer set search_path = public as $$
declare q json := ai_quota(); lim int := (q->>'limit')::int; ay_ text := to_char(now() at time zone 'Europe/Istanbul', 'YYYY-MM');
begin
  if auth.uid() is null or not is_active() then return false; end if;
  insert into ai_usage (user_id, ay, n) values (auth.uid(), ay_, 1)
  on conflict (user_id, ay) do update set n = ai_usage.n + 1
  where lim is null or ai_usage.n < lim;
  if found then return true; end if;
  update profiles set ai_credits = ai_credits - 1 where id = auth.uid() and ai_credits > 0;
  return found;
end $$;

-- Üye: kredi paketi talebi (ödemeyi yaptıktan sonra)
create or replace function public.request_credit(pkg text) returns bigint
language plpgsql security definer set search_path = public as $$
declare f int; oid bigint;
begin
  if not is_active() then raise exception 'aktif abonelik gerekli'; end if;
  select fiyat into f from ai_packages where code = pkg; if f is null then raise exception 'paket yok'; end if;
  if (select count(*) from credit_orders where user_id = auth.uid() and status = 'pending') >= 3 then raise exception 'bekleyen talep çok'; end if;
  insert into credit_orders (user_id, code, fiyat) values (auth.uid(), pkg, f) returning id into oid;
  return oid;
end $$;

-- Yönetici: kredi talebini onayla / reddet
create or replace function public.decide_credit(oid bigint, ok boolean) returns void
language plpgsql security definer set search_path = public as $$
declare o credit_orders; pk ai_packages;
begin
  if not exists (select 1 from profiles where id = auth.uid() and role = 'admin') then raise exception 'yetkisiz'; end if;
  select * into o from credit_orders where id = oid and status = 'pending' for update; if o.id is null then return; end if;
  update credit_orders set status = case when ok then 'approved' else 'rejected' end, decided_at = now() where id = oid;
  if not ok then return; end if;
  select * into pk from ai_packages where code = o.code;
  if pk.gun is not null then
    update profiles set ai_sinirsiz_until = greatest(coalesce(ai_sinirsiz_until, now()), now()) + make_interval(days => pk.gun) where id = o.user_id;
  else
    update profiles set ai_credits = ai_credits + pk.adet where id = o.user_id;
  end if;
end $$;

-- Yönetici: üyeye sınırsız asistan aç/kapat
create or replace function public.set_ai_unlimited(uid uuid, val boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from profiles where id = auth.uid() and role = 'admin') then raise exception 'yetkisiz'; end if;
  update profiles set ai_unlimited = val where id = uid;
end $$;

grant execute on function public.ai_quota(), public.use_ai_quota(), public.request_credit(text),
  public.decide_credit(bigint, boolean), public.set_ai_unlimited(uuid, boolean) to authenticated;
notify pgrst, 'reload schema';
