-- TMPRO: Haberler sekmesi + profilde ünvan / birim / promosyon + argo engeli

-- 1) Haberler (yalnızca aktif üyeler okur; GitHub Actions servis anahtarıyla yazar)
create table if not exists public.news (
  id bigserial primary key,
  title text not null,
  url text not null unique,
  source text,
  konu text,                       -- hangi aramadan geldi (VDK, Bakanlık, GİB…)
  published timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists news_pub_idx on public.news (published desc);
alter table public.news enable row level security;
drop policy if exists "haber: aktif üyeler" on public.news;
create policy "haber: aktif üyeler" on public.news for select using (is_active());
grant select on public.news to authenticated;

-- 2) Argo / küfür denetimi (uygulama da aynı listeyle anında uyarır)
create or replace function public.has_argo(t text) returns boolean
language sql immutable as $$
  select coalesce(
    regexp_replace(translate(lower(replace(replace(t, 'İ', 'i'), 'I', 'ı')), '013457@$€', 'oieastase'), '([[:alpha:]])[.*_-]+(?=[[:alpha:]])', '\1', 'g')
      ~* ('(^|[^[:alpha:]])(am|amk|amq|aq|amın|amina|oç|göt|piç|pic|sik|sikerim|ibne|puşt|pust|gavat|kaltak|kahpe|yarak|yarrak|taşak|tassak|daşşak|dassak|orospu|orosbu|pezevenk|yavşak|yavsak|şerefsiz|serefsiz|amcık|amcik|amck|siktir|sktr)([^[:alpha:]]|$)'
         || '|(amcı|amcik|amına|amini|amını|orosp|orosb|sikt|sikiş|sikis|sikik|sikim|siker|sikey|yarra|dalyar|taşşa|daşşa|götve|gotve|götle|pezev|kahpe|kaltak|yavşa|ananı|anani|bacını|ibneli)')
  , false)
$$;

-- 3) Profil alanları
alter table public.profiles add column if not exists birim text;
alter table public.profiles add column if not exists promosyon text;
alter table public.profiles drop constraint if exists profiles_unvan_check;
alter table public.profiles add constraint profiles_unvan_check check (char_length(unvan) <= 140);

create or replace function public.profiles_argo_guard() returns trigger
language plpgsql as $$
begin
  if has_argo(new.unvan) or has_argo(new.birim) or has_argo(new.promosyon) or has_argo(new.full_name) then
    raise exception 'Uygunsuz ifade kullanılamaz' using errcode = '22023';
  end if;
  return new;
end $$;
drop trigger if exists profiles_argo on public.profiles;
create trigger profiles_argo before insert or update of unvan, birim, promosyon, full_name on public.profiles
  for each row execute function public.profiles_argo_guard();

-- Ünvan, birim ve promosyon ayrı saklanır; sohbette görünen "unvan" üçünün birleşimidir
create or replace function public.set_my_titles(u text, b text, p text) returns text
language plpgsql security definer set search_path = public as $$
declare uu text := nullif(left(trim(u), 60), ''); bb text := nullif(left(trim(b), 60), ''); pp text := nullif(left(trim(p), 40), ''); birlesik text;
begin
  if has_argo(uu) or has_argo(bb) or has_argo(pp) then
    raise exception 'Uygunsuz ifade kullanılamaz' using errcode = '22023';
  end if;
  birlesik := nullif(concat_ws(' · ', uu, bb, pp), '');
  update profiles set unvan = birlesik, birim = bb, promosyon = pp where id = auth.uid();
  return birlesik;
end $$;
grant execute on function public.set_my_titles(text, text, text) to authenticated;

-- 4) Sohbet: mesaj düzenleme ve özel mesajda okundu bilgisi (mavi tik)
alter table public.messages add column if not exists edited_at timestamptz;
create or replace function public.edit_message(mid bigint, newbody text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if char_length(trim(newbody)) < 1 then raise exception 'Boş mesaj' using errcode = '22023'; end if;
  update messages set body = left(trim(newbody), 2000), edited_at = now() where id = mid and user_id = auth.uid();
end $$;
grant execute on function public.edit_message(bigint, text) to authenticated;

create table if not exists public.room_reads (
  room text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  last_id bigint not null default 0,
  updated_at timestamptz not null default now(),
  primary key (room, user_id)
);
alter table public.room_reads enable row level security;
drop policy if exists "okundu: oda tarafları görür" on public.room_reads;
create policy "okundu: oda tarafları görür" on public.room_reads for select using (is_active() and can_see_room(room));
grant select on public.room_reads to authenticated;
create or replace function public.mark_read(r text, mid bigint) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not can_see_room(r) then return; end if;
  insert into room_reads (room, user_id, last_id) values (r, auth.uid(), mid)
  on conflict (room, user_id) do update set last_id = greatest(room_reads.last_id, excluded.last_id), updated_at = now();
end $$;
grant execute on function public.mark_read(text, bigint) to authenticated;
do $$ begin
  alter publication supabase_realtime add table public.room_reads;
exception when duplicate_object then null; end $$;

notify pgrst, 'reload schema';
