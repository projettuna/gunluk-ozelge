-- TMPRO · Şifremi unuttum, Sorun Bildir / Öneri, kullanım istatistiği
-- Tekrar çalıştırılabilir. (eposta.sql ve kvkk.sql'den sonra)

-- ============================================================ 1) Şifre sıfırlama
create table if not exists public.password_resets (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);
alter table public.password_resets enable row level security;  -- politika yok: yalnızca fonksiyonlar

-- Kullanıcı adı + kayıtlı e-posta eşleşirse e-postaya 1 saat geçerli sıfırlama bağlantısı gider.
-- Bilgiler eşleşmese de aynı yanıt döner (hesap var mı yok mu belli olmasın).
create or replace function public.request_password_reset(uname text, addr text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare p profiles; tok text;
begin
  select * into p from profiles where username = lower(trim(uname)) and lower(email) = lower(trim(addr));
  if not found or p.email is null then perform pg_sleep(0.3); return; end if;
  if (select count(*) from password_resets where user_id = p.id and created_at > now() - interval '1 hour') >= 3 then return; end if;
  tok := encode(gen_random_bytes(24), 'hex');
  insert into password_resets (user_id, token_hash, expires_at)
  values (p.id, encode(digest(tok, 'sha256'), 'hex'), now() + interval '1 hour');
  perform queue_mail(p.email, 'TMPRO şifre sıfırlama',
    'Merhaba ' || coalesce(p.full_name, p.username) || ',' || E'\n\n' ||
    'TMPRO hesabınız (@' || p.username || ') için şifre sıfırlama istendi. Yeni şifrenizi belirlemek için bağlantıya dokunun (1 saat geçerlidir):' || E'\n\n' ||
    'https://tmpro.tmproapp.workers.dev/?sifre=' || tok || E'\n\n' ||
    'Bu isteği siz yapmadıysanız bu e-postayı dikkate almayın; şifreniz değişmez.');
end $$;

create or replace function public.reset_password(tok text, newpw text) returns boolean
language plpgsql security definer set search_path = public, extensions as $$
declare r password_resets;
begin
  if newpw is null or char_length(newpw) < 8 then raise exception 'Şifre en az 8 karakter olmalı'; end if;
  select * into r from password_resets where token_hash = encode(digest(coalesce(tok, ''), 'sha256'), 'hex')
    and used_at is null and expires_at > now();
  if not found then return false; end if;
  update auth.users set encrypted_password = crypt(newpw, gen_salt('bf')), updated_at = now() where id = r.user_id;
  update password_resets set used_at = now() where user_id = r.user_id and used_at is null;
  return true;
end $$;

-- Yönetici bir üyenin şifresini elle değiştirebilir (e-postası olmayanlar için)
create or replace function public.admin_set_password(uid uuid, newpw text) returns void
language plpgsql security definer set search_path = public, extensions as $$
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  if newpw is null or char_length(newpw) < 8 then raise exception 'Şifre en az 8 karakter olmalı'; end if;
  update auth.users set encrypted_password = crypt(newpw, gen_salt('bf')), updated_at = now() where id = uid;
end $$;

grant execute on function public.request_password_reset(text, text), public.reset_password(text, text) to anon, authenticated;
grant execute on function public.admin_set_password(uuid, text) to authenticated;

-- ============================================================ 2) Sorun Bildir / Öneri
create table if not exists public.feedback (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  kind text not null check (kind in ('sorun', 'oneri', 'soru')),
  body text not null check (char_length(body) between 3 and 2000),
  page text, ua text,
  status text not null default 'acik' check (status in ('acik', 'cozuldu')),
  reply text,
  created_at timestamptz not null default now()
);
alter table public.feedback enable row level security;
drop policy if exists "geri bildirim: kendisi veya yönetici görür" on public.feedback;
create policy "geri bildirim: kendisi veya yönetici görür" on public.feedback for select using (user_id = auth.uid() or is_admin());
grant select on public.feedback to authenticated;

create or replace function public.send_feedback(k text, b text, pg text default null, u text default null) returns void
language plpgsql security definer set search_path = public as $$
declare nm text;
begin
  if auth.uid() is null then raise exception 'yetkisiz'; end if;
  if (select count(*) from feedback where user_id = auth.uid() and created_at > now() - interval '1 day') >= 15 then
    raise exception 'Bugün çok fazla bildirim gönderdiniz';
  end if;
  insert into feedback (kind, body, page, ua) values (k, trim(b), left(pg, 40), left(u, 300));
  select coalesce(full_name, username) into nm from profiles where id = auth.uid();
  perform notify_admins(case k when 'sorun' then '🐞 Sorun bildirildi' when 'oneri' then '💡 Yeni öneri' else '❓ Yeni soru' end,
                        coalesce(nm, 'Üye') || ': ' || left(trim(b), 140));
end $$;

create or replace function public.admin_feedback(fid bigint, done boolean, answer text default null) returns void
language plpgsql security definer set search_path = public as $$
declare f feedback;
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  update feedback set status = case when done then 'cozuldu' else 'acik' end,
                      reply = coalesce(nullif(trim(answer), ''), reply)
  where id = fid returning * into f;
  if nullif(trim(answer), '') is not null then
    perform notify_user(f.user_id, 'TMPRO yanıtladı', left(trim(answer), 160));
  end if;
end $$;
grant execute on function public.send_feedback(text, text, text, text), public.admin_feedback(bigint, boolean, text) to authenticated;

-- ============================================================ 3) Kullanım istatistiği (yalnızca yönetici görür)
create table if not exists public.usage_daily (
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null default (now() at time zone 'Europe/Istanbul')::date,
  kind text not null,
  n int not null default 1,
  primary key (user_id, day, kind)
);
alter table public.usage_daily enable row level security;  -- politika yok: yalnızca fonksiyonlar

create or replace function public.track(k text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null or k is null or k !~ '^[a-z_]{2,20}$' then return; end if;
  insert into usage_daily (user_id, kind) values (auth.uid(), k)
  on conflict (user_id, day, kind) do update set n = least(usage_daily.n + 1, 1000);
end $$;
grant execute on function public.track(text) to authenticated;

create or replace function public.usage_summary(days int default 30) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare since date := (now() at time zone 'Europe/Istanbul')::date - greatest(days - 1, 0);
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  return jsonb_build_object(
    'daily', (select coalesce(jsonb_agg(jsonb_build_object('day', d.day, 'users', d.u) order by d.day), '[]')
              from (select day, count(distinct user_id) u from usage_daily where day >= since group by day) d),
    'kinds', (select coalesce(jsonb_object_agg(k.kind, k.t), '{}')
              from (select kind, sum(n) t from usage_daily where day >= since group by kind) k),
    'users', (select coalesce(jsonb_agg(jsonb_build_object('name', coalesce(p.full_name, p.username), 'unvan', p.unvan,
                       'last', x.last, 'days', x.days, 'opens', x.opens, 'top', x.top) order by x.last desc), '[]')
              from (select user_id, max(day) last, count(distinct day) days,
                           coalesce(sum(n) filter (where kind = 'acilis'), 0) opens,
                           (select string_agg(kind, ', ' order by s desc) from
                              (select kind, sum(n) s from usage_daily u2 where u2.user_id = u.user_id and u2.day >= since
                               and kind <> 'acilis' group by kind order by sum(n) desc limit 3) t) top
                    from usage_daily u where day >= since group by user_id) x
              join profiles p on p.id = x.user_id));
end $$;
grant execute on function public.usage_summary(int) to authenticated;

notify pgrst, 'reload schema';
