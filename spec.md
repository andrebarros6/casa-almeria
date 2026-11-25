# Almería Rental Finder — Spec

## What it is
A private tool for two people (the owner and their partner) to find a long-term rental in Almería. Every day it collects matching listings from several property portals, removes duplicates, and shows them on one shared web page. It also sends new matches to a shared Telegram chat.

## What it is not
- Not a public product: there are only two users and no sign-up.
- Not for buying property or holiday rentals.
- Not a replacement for contacting agents: it links back to the original listing.
- Not a high-volume scraper: one search per area per source per day.

## Users
- The owner and their partner, logging in by magic link with two whitelisted emails. Both use it mostly on their phones.

## Core loop
1. Each morning, scrapers collect listings that match `config/search.yaml`.
2. Listings are normalised, filtered and deduplicated across portals, then stored.
3. New matches and price drops are sent to Telegram.
4. Both partners browse the page, mark ❤️ or ❌ and leave notes. These are shared between them.

## Sources
| Source | Runs on | Method | Status (2026-11-25) |
|---|---|---|---|
| pisos.com | GitHub Actions | HTTP + HTML parsing | ✅ working |
| enalquiler | GitHub Actions | HTTP + HTML (whole province, filtered by town) | ✅ working |
| Fotocasa | Owner's Windows PC | Playwright, real Chrome; data from embedded JSON | ✅ working |
| Idealista | — | — | ❌ DataDome 403/captcha in real Chrome |
| yaencontre | — | — | ❌ search page loads, detail pages DataDome-blocked |
| Milanuncios | — | — | ❌ Imperva "Pardon Our Interruption" |

tucasa.com was dropped: its domain no longer resolves.
Idealista, yaencontre and Milanuncios are read from their saved-search alert emails in a dedicated Gmail (IMAP). See README.
The PC-based sources only run when the PC is on. If a source is blocked or returns nothing, the page and Telegram say so.

## Stack
Python 3.12 (scrapers and pipeline) · Supabase (Postgres + Auth + RLS) · GitHub Pages (Vite + TypeScript + Leaflet) · GitHub Actions (cron) · Windows Task Scheduler · Telegram Bot API · OpenRouteService (commute times).

## Known risks
- Idealista and Fotocasa terms forbid scraping, and they use bot protection. Accepted for low-volume personal use. Expect breakage.
- Portal HTML changes break parsers. Parser tests use saved fixtures, and source health is monitored.
