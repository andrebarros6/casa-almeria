# Setup checklist

Steps marked **You** need your accounts or eyes. Steps marked **Claude** I can do once you say go.
Check progress any time with:
```powershell
.venv\Scripts\python -m scraper.check_setup
```

## A. Supabase (You, ~5 min). Required.
1. **SQL Editor → New query**, paste and **Run**:
   ```sql
   grant usage on schema public to service_role, authenticated;
   grant all on listings, source_runs, reactions, allowed_users to service_role;
   grant usage, select on all sequences in schema public to service_role;
   grant select on listings, source_runs, allowed_users to authenticated;
   grant select, insert, update, delete on reactions to authenticated;
   revoke all on listings, source_runs, reactions, allowed_users from anon;
   ```
2. If you skipped it before: in a new query, add both of you (use your real emails and names):
   ```sql
   insert into allowed_users (email, display_name)
   values ('you@example.com', 'YourName'), ('partner@example.com', 'PartnerName');
   ```
3. **Authentication → Users → Add user → Create new user**, once per email. Use the same emails, tick **Auto Confirm User**, any password.
4. In `.env`, fill in `COMMUTE_ADDRESS=` (your work address).

➜ Then tell Claude **"Supabase done"**. **Claude** runs the checker and the first real scrape into Supabase.

## B. Telegram (You, ~5 min). Recommended.
5. In Telegram, message **@BotFather** → `/newbot` → pick a name → copy the **token** into `.env` as `TELEGRAM_BOT_TOKEN=`.
6. Create a **group** with the two of you and add the bot.
7. Send any message in the group. Then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in your browser and copy the `"chat":{"id":-…}` number into `.env` as `TELEGRAM_CHAT_ID=`.

➜ **Claude** sends a test message with `check_setup --telegram-test`.

## C. Alert Gmail (You, ~20 min). Covers Idealista, yaencontre and Milanuncios.
8. Create a **new Gmail account** just for this.
9. Turn on **2-Step Verification** (myaccount.google.com → Security).
10. Create an **app password** (myaccount.google.com/apppasswords) and put it in `.env` with the address: `ALERTS_EMAIL=` and `ALERTS_APP_PASSWORD=`.
11. Signed in with that Gmail, save searches with **daily email alerts** on **Idealista**, **yaencontre** and **Milanuncios**: long-term rental, ≤ €1,000, 2+ bedrooms, for Almería capital, Roquetas de Mar (Aguadulce), El Ejido (Almerimar), Níjar, Carboneras, Mojácar and Vera.

➜ After the first alert emails arrive, **Claude** tunes the email parsers against them.

## D. Publish (Claude, after you say go)
12. **Claude:** create the **public** GitHub repo, upload all secrets straight from `.env` (values never shown), commit one feature per commit, push, and turn on GitHub Pages.
13. **You:** Supabase → **Authentication → URL Configuration**: set **Site URL** to the page address Claude gives you, and add it under **Redirect URLs**.
14. **Claude:** trigger the first cloud run and the page deploy, then check both.

## E. This PC (Fotocasa)
15. **Claude** (with your OK) or **You**: register the daily task. See README "PC sources". At about 09:00 a Chrome window opens for a few minutes; leave it alone.

## F. Go live
16. **Both of you:** open the page on your phones and log in with the email link.
17. **Claude:** run a `test-app` pass (are the database rules really locked down? are any keys exposed?) before you rely on it.
