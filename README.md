# Almería Rental Finder

Collects long-term rentals in Almería from several portals every day, filters and deduplicates them, and stores them in Supabase for a shared web page. See [spec.md](spec.md) and [prd.md](prd.md). Search criteria live in [config/search.yaml](config/search.yaml).

## Local setup
```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

## Run
```powershell
# Dry run: writes to out/listings.json, no Supabase needed
.venv\Scripts\python -m scraper.run --sources cloud --dry-run --max-details 10

# Real run (reads SUPABASE_URL / SUPABASE_SERVICE_KEY from .env)
.venv\Scripts\python -m scraper.run --sources cloud
```
`--sources` takes `cloud`, `local`, `all`, or names (`pisos,enalquiler`).

## Supabase (one-off)
1. Create a project at supabase.com (free tier).
2. In **SQL editor**, paste [supabase/schema.sql](supabase/schema.sql). Edit the last line with both emails, uncomment it, and run it.
3. In **Project Settings → API**, copy the Project URL and the `service_role` key into `.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_SERVICE_KEY=eyJ...
   ```
   The service key bypasses all security rules. Keep it only in `.env` (git-ignored) and in GitHub secrets.
4. Also add `COMMUTE_ADDRESS=<your work address>` to `.env`. It's kept out of the repo, which is public.

## GitHub (one-off)
1. Create a **public** repo (free GitHub Pages) and push this folder. Nothing personal is in the code: addresses, emails and keys live in `.env` and GitHub secrets, and your data lives in Supabase behind login.
2. In **Settings → Secrets and variables → Actions**, add `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY` and `COMMUTE_ADDRESS`.
3. **Actions → Daily scrape → Run workflow** tests it immediately. After that it runs daily at 07:00 Madrid time.

## PC sources (Fotocasa)
Fotocasa needs a real Chrome window, so it runs on this PC rather than GitHub.
```powershell
.venv\Scripts\pip install -e ".[local]"
```
Register the daily task once (runs at 16:00 plus a random 0–20 min, close to when the cloud digest tends to land):
```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"E:\projects\almeria\local\run_local.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At 16:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Almeria rental finder" -Action $action -Trigger $trigger -Settings $settings
```
`-StartWhenAvailable` means that if the PC was off at 16:00, the task runs as soon as it's back on. Logs go to `local\logs\`. A Chrome window opens for a few minutes while it runs; leave it alone.

## Alert emails (Idealista, yaencontre, Milanuncios)
These portals block automated browsing, so we read their saved-search alert emails instead.
1. Create a **new Gmail account** used only for this.
2. Turn on **2-Step Verification**: myaccount.google.com → Security.
3. Create an **app password**: myaccount.google.com/apppasswords → name it "almeria". Copy the 16 characters.
4. While logged in with the new Gmail, save a search with **daily email alerts** on each portal: long-term rental, ≤ €1,000, 2+ bedrooms, for each area (Almería city, Roquetas/Aguadulce, El Ejido/Almerimar, Níjar, Carboneras, Mojácar, Vera).
5. Add to `.env` and to the GitHub secrets:
   ```
   ALERTS_EMAIL=the-new-address@gmail.com
   ALERTS_APP_PASSWORD=abcdefghijklmnop
   ```
The email sources join the daily run automatically once both values are set. Listings from emails have no feature data (lift, A/C), so they skip the must-have filter and are labelled "check features" on the page.

## Telegram digest
After each run, new flats (photo, price, the catch, link), price drops, and a warning when a source fails twice in a row.
1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Create a group with the two of you and add the bot.
3. Send any message in the group, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `chat.id` (a negative number).
4. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `.env` and to the GitHub secrets.

Dry runs don't send unless you pass `--notify`. To test with the local data:
```powershell
.venv\Scripts\python -m scraper.run --sources enalquiler --dry-run --max-details 3 --notify
```

## Web page
Phone-first page in `web/` (Vite + TypeScript + Tailwind). Design decisions are in [design-guidelines.md](design-guidelines.md).

**Local preview** (no Supabase needed; uses the dry-run data):
```powershell
copy out\listings.json web\public\sample.json
cd web ; npm install ; npm run dev
```
**Publishing** (GitHub Pages):
1. Supabase → **Authentication → Users → Add user**: add both emails. The page never creates accounts.
2. Supabase → **Authentication → URL Configuration**: set Site URL to `https://<github-user>.github.io/<repo>/` and add it to Redirect URLs.
3. GitHub secrets: add `SUPABASE_ANON_KEY` (Project Settings → API → `anon` key; safe to publish because row-level security restricts it).
4. GitHub → **Settings → Pages → Source: GitHub Actions**. Pushing to `main` builds and deploys.

Run the web checks from `E:\` with an uppercase drive letter. On Windows, Vitest breaks if the drive letter's case doesn't match.
```powershell
cd E:\projects\almeria\web ; npm run lint ; npm run typecheck ; npm test
```

## Checks
```powershell
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check . ; .venv\Scripts\mypy scraper tests ; .venv\Scripts\pytest
```
