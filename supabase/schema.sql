-- TMPRO veritabanı şeması (Supabase / Postgres)

-- Profiller: her kullanıcı için abonelik durumu
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique not null,
  full_name text,
  phone text,
  role text not null default 'user' check (role in ('user','admin')),
  status text not null default 'pending' check (status in ('pending','active','rejected','cancelled')),
  expires_at timestamptz,               -- null + active = süresiz
  pay_code text,
  notify_types text[] not null default array['Özelge','Tebliğ','Sirküler','Kanun','CB Kararı','İç Genelge','Resmî Gazete','Danıştay (VUK 359)','Anayasa Mahkemesi'],
  last_notified_at timestamptz not null default now(),
  note text,
  created_at timestamptz not null default now(),
  approved_at timestamptz
);

-- Mevzuat kayıtları
create table if not exists public.items (
  id bigserial primary key,
  tur text not null,
  title text not null,
  meta text,
  url text,
  ozet text,
  eklendi timestamptz,                   -- null = ilk yüklemedeki eski kayıtlar
  created_at timestamptz not null default now(),
  unique (tur, url, title)
);
create index if not exists items_created_idx on public.items (created_at desc);

-- Anlık bildirim abonelikleri (Web Push)
create table if not exists public.push_subs (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text unique not null,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);

-- Herkese açık ayarlar (IBAN, alıcı, fiyat) ve gizli ayarlar
create table if not exists public.settings (key text primary key, value text);
create table if not exists public.private_settings (key text primary key, value text);
insert into public.settings (key, value) values
  ('iban',''), ('alici',''), ('fiyat','99'), ('sure_gun','30')
on conflict (key) do nothing;

-- Yardımcı fonksiyonlar
create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where id = auth.uid() and role = 'admin');
$$;

create or replace function public.is_active() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where id = auth.uid()
                 and (role = 'admin' or (status = 'active' and (expires_at is null or expires_at > now()))));
$$;

-- Yeni kullanıcı kaydında profil oluştur (kullanıcı adı, ad soyad, telefon kayıt sırasında gelir)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, username, full_name, phone, pay_code)
  values (new.id,
          lower(coalesce(new.raw_user_meta_data->>'username', split_part(new.email, '@', 1))),
          new.raw_user_meta_data->>'full_name',
          new.raw_user_meta_data->>'phone',
          'TM' || lpad((floor(random() * 900000) + 100000)::int::text, 6, '0'));
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Yönetici işlemleri
create or replace function public.admin_approve(uid uuid, days int default null) returns void
language plpgsql security definer set search_path = public as $$
declare d int;
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  d := coalesce(days, (select value::int from settings where key = 'sure_gun'), 30);
  update profiles set status = 'active', approved_at = now(),
    expires_at = case when d <= 0 then null
                      else greatest(coalesce(expires_at, now()), now()) + make_interval(days => d) end
  where id = uid;
end $$;

create or replace function public.admin_set_status(uid uuid, new_status text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  update profiles set status = new_status where id = uid;
end $$;

-- Kullanıcının kendi bildirim tercihleri
create or replace function public.set_my_notify_types(types text[]) returns void
language sql security definer set search_path = public as $$
  update profiles set notify_types = types where id = auth.uid();
$$;

-- Kullanıcı adının kullanılıp kullanılmadığı (kayıt formu için)
create or replace function public.username_taken(u text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where username = lower(u));
$$;

-- Satır düzeyi güvenlik
alter table public.profiles enable row level security;
alter table public.items enable row level security;
alter table public.push_subs enable row level security;
alter table public.settings enable row level security;
alter table public.private_settings enable row level security;

drop policy if exists "profil: kendisi veya yönetici" on public.profiles;
create policy "profil: kendisi veya yönetici" on public.profiles for select using (id = auth.uid() or is_admin());
drop policy if exists "profil: yönetici günceller" on public.profiles;
create policy "profil: yönetici günceller" on public.profiles for update using (is_admin());

drop policy if exists "kayıtlar: aktif aboneler" on public.items;
create policy "kayıtlar: aktif aboneler" on public.items for select using (is_active());

drop policy if exists "push: kendi aboneliği" on public.push_subs;
create policy "push: kendi aboneliği" on public.push_subs for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "ayarlar: herkes okur" on public.settings;
create policy "ayarlar: herkes okur" on public.settings for select using (true);
drop policy if exists "ayarlar: yönetici yazar" on public.settings;
create policy "ayarlar: yönetici yazar" on public.settings for update using (is_admin());
-- private_settings için politika yok: sadece servis anahtarı okur.

grant execute on function public.username_taken(text) to anon, authenticated;
