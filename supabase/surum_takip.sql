-- TMPRO · Üyenin kullandığı uygulama sürümü. Eski sürümde kalanlara her yeni sürüm için bir kez hatırlatma gider.
-- Tekrar çalıştırılabilir.
alter table public.profiles add column if not exists app_version text;
alter table public.profiles add column if not exists app_mode text;          -- 'uygulama' (ana ekrandan) / 'tarayici'
alter table public.profiles add column if not exists app_seen_at timestamptz;
alter table public.profiles add column if not exists version_reminded text; -- en son hangi sürüm için hatırlatıldı

create or replace function public.set_app_version(v text, m text) returns void
language sql security definer set search_path = public as $$
  update profiles set app_version = left(v, 12), app_mode = left(m, 12), app_seen_at = now() where id = auth.uid();
$$;
grant execute on function public.set_app_version(text, text) to authenticated;
notify pgrst, 'reload schema';
