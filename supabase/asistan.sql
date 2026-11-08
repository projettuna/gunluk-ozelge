-- TMPRO: Mevzuat asistanı sohbetleri (her üye yalnızca kendi sohbetlerini görür)
create table if not exists public.ai_chats (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text not null default 'Yeni sohbet' check (char_length(title) <= 120),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.ai_messages (
  id bigserial primary key,
  chat_id bigint not null references public.ai_chats(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null check (char_length(content) <= 20000),
  sources jsonb,
  files jsonb,                               -- yalnızca dosya adları (dosyanın kendisi saklanmaz)
  created_at timestamptz not null default now()
);
create index if not exists ai_messages_chat_idx on public.ai_messages (chat_id, id);
alter table public.ai_chats enable row level security;
alter table public.ai_messages enable row level security;
drop policy if exists "asistan: kendi sohbetleri" on public.ai_chats;
create policy "asistan: kendi sohbetleri" on public.ai_chats for all using (user_id = auth.uid()) with check (user_id = auth.uid() and is_active());
drop policy if exists "asistan: kendi mesajları" on public.ai_messages;
create policy "asistan: kendi mesajları" on public.ai_messages for all using (user_id = auth.uid())
  with check (user_id = auth.uid() and exists (select 1 from ai_chats c where c.id = chat_id and c.user_id = auth.uid()));
grant select, insert, update, delete on public.ai_chats, public.ai_messages to authenticated;
grant usage on sequence public.ai_chats_id_seq, public.ai_messages_id_seq to authenticated;
notify pgrst, 'reload schema';
