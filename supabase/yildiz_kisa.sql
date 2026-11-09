-- TMPRO · Gizli adlarda daha az yıldız: "Merve Yılmaz" → "M** Y**". Tekrar çalıştırılabilir.
create or replace function public.mask_name(n text) returns text
language sql immutable as $$
  select coalesce(string_agg(left(w, 1) || '**', ' '), '**')
  from regexp_split_to_table(trim(coalesce(n, '')), '\s+') w where w <> '';
$$;
-- Eski mesajlarda kayıtlı adlar da güncellensin
update public.messages m set username = public_name(m.user_id) where username is distinct from public_name(m.user_id);
notify pgrst, 'reload schema';
