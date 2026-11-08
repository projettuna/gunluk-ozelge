-- TMPRO · Profil fotoğrafı
-- Fotoğraf uygulamada 256x256 küçültülüp profiles.avatar alanına (data URL) kaydedilir.
alter table public.profiles add column if not exists avatar text;

create or replace function public.set_my_avatar(a text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if a is not null and (a !~ '^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$' or length(a) > 120000) then
    raise exception 'Geçersiz fotoğraf';
  end if;
  update profiles set avatar = nullif(a, '') where id = auth.uid();
end $$;
grant execute on function public.set_my_avatar(text) to authenticated;

drop function if exists public.list_members();
create or replace function public.list_members() returns table (id uuid, username text, full_name text, unvan text, avatar text)
language sql stable security definer set search_path = public as $$
  select p.id, p.username, p.full_name, p.unvan, p.avatar from profiles p
  where is_active() and p.id <> auth.uid()
    and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now())))
  order by coalesce(p.full_name, p.username);
$$;
grant execute on function public.list_members() to authenticated;
