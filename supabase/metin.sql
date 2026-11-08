-- TMPRO: kayıtların tam metni ve müfettiş notu
alter table public.items add column if not exists metin text;   -- null = henüz alınmadı, '' = kaynaktan alınamıyor
alter table public.items add column if not exists yorum text;   -- "Müfettiş Notu" (yapay zekâ yorumu)
create index if not exists items_metin_bekleyen_idx on public.items (id desc) where metin is null;
notify pgrst, 'reload schema';
