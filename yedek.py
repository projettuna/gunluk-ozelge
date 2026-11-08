#!/usr/bin/env python3
"""TMPRO gece yedeği: veritabanı tablolarını JSON olarak yedek/ klasörüne indirir.

Şifreleme ve saklama iş akışında yapılır (yedek.yml): dosyalar AES-256 ile şifrelenip
GitHub'da 30 gün saklanır. Depo herkese açık olduğu için burada yalnızca tablo adları ve satır sayıları yazdırılır.
"""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
OUT = "yedek"
TABLES = ["profiles", "friendships", "messages", "chat_groups", "chat_group_members", "room_reads", "user_events",
          "credit_orders", "ai_usage", "ai_packages", "ai_chats", "ai_messages", "settings", "private_settings",
          "consent_log", "banned", "feedback", "usage_daily", "push_subs", "mail_queue", "news", "items"]


def h():
    x = {"apikey": KEY}
    if KEY.startswith("eyJ"):
        x["Authorization"] = f"Bearer {KEY}"
    return x


def get(url):
    with urlopen(Request(url, headers=h()), timeout=120) as r:
        return json.loads(r.read() or b"[]")


def dump(table):
    rows, off, order = [], 0, "&order=id"
    while True:
        try:
            part = get(f"{SB}/rest/v1/{table}?select=*{order}&limit=1000&offset={off}")
        except HTTPError as e:
            if e.code == 400 and order:  # tabloda id sütunu yok
                order = ""
                continue
            raise
        rows += part
        if len(part) < 1000:
            return rows
        off += 1000


def main():
    os.makedirs(OUT, exist_ok=True)
    total = {}
    for t in TABLES:
        try:
            rows = dump(t)
        except HTTPError as e:
            print(f"{t}: atlandı (HTTP {e.code})")
            continue
        with open(os.path.join(OUT, t + ".json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        total[t] = len(rows)
    # Giriş hesapları (şifreler hariç; Supabase şifre özetini dışarı vermez)
    users, page = [], 1
    while True:
        j = get(f"{SB}/auth/v1/admin/users?page={page}&per_page=1000")
        part = j.get("users", []) if isinstance(j, dict) else j
        users += part
        if len(part) < 1000:
            break
        page += 1
    with open(os.path.join(OUT, "auth_users.json"), "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False)
    total["auth_users"] = len(users)
    print("Yedeklenen satırlar:", total)
    with open(os.path.join(OUT, "ozet.json"), "w", encoding="utf-8") as f:
        json.dump(total, f)


if __name__ == "__main__":
    main()
