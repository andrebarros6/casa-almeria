# Almería Rental Finder — PRD

## Goal
Find and sign a suitable long-term rental faster and with less daily effort, and make the decision together.

## Success
- Both partners check one page instead of 5+ portals.
- A listing is seen within 24h of being published (or within 24h of the PC being on, for local sources).
- The same flat appears once, even when it's on several portals.

## Requirements

### Must (v1)
- **Search criteria** live in `config/search.yaml`: long-term rental, 2+ bedrooms, flat or house, ≤ €1,000/month, areas (Almería city, west coast, east coast).
- **Hard filters:** within budget, 2+ bedrooms, must-have features (a flat needs a lift or A/C; a house needs A/C), and no short-term or seasonal rentals (portal filter + keyword blocklist).
- **Daily collection** from the 7 sources listed in spec.md, with a per-source health status.
- **Cross-portal dedupe:** one card per flat, linking to every portal that lists it.
- **Tracking:** first seen, last seen, price history, and listings marked "gone" after 3 days unseen.
- **Shared page:** photo cards plus a map. Filters: price, bedrooms, area, source, terrace, parking, pets, furnished, new today, price dropped, hide ❌.
- **Shared reactions:** ❤️ / ❌ / free-text note per listing, visible to both partners. Includes a shortlist view.
- **Ranking:** furnished first, then shortest commute to the configured address.
- **Telegram digest** of new matches and price drops, plus an alert when a source fails 2 days in a row.
- **Private access:** magic-link login for 2 whitelisted emails only.

### Must (v1.1, agreed 2026-11-26)
- **"A procurar" line** at the top of the page: the fixed search criteria in plain words, plus an ⓘ showing how many listings each rule discarded on the latest run. The scraper saves the criteria and counts to Supabase, so the page always matches what was actually searched.
- **Chip row:** always-visible one-tap filters (≤900 €, 3+ quartos, mobilado, terraço, garagem, animais, ar cond., Almería / Poniente / Levante). The "Filtros" sheet keeps the rest.
- **Stronger dedupe:** same bedrooms, price ±3% and m² ±5%, plus *either* pins within 150 m *or* descriptions ≥90% identical. Portals geocode the same flat up to km apart, and agencies reuse template text for different flats. Whole cards merge, ❤️/notes move to the surviving card, and the map uses the median pin of a card's listings.

### Must (v1.2, agreed 2026-11-26): lead tracker
Promoted from "visit tracking" under *Should*.
- **Stages per card**, shared by both: Interessa (❤️) → Contactado → Respondeu → Visita marcada → Visitado → Candidatura → Fechado, with side exits Sem resposta, Já alugado and Descartado (with a reason).
- **Contacting:** the portal contact form is the main channel. A ready-made Spanish message from both partners is copied to the clipboard and the listing opens, so it can be pasted into the form. An email button appears only when the listing shows an address (2/261 today). Nothing is ever sent automatically. "Já enviei" logs who contacted, how and when.
- **Timeline per lead:** stage changes, replies, visit date and time, and notes, with who and when.
- **"Contactos" tab:** leads grouped by stage, next action first.
- **Telegram nudges** in the daily digest: no reply 2 and 5 days after contact, and visits in the next 24 h.
- **Documents checklist** (household, not per flat): DNI/NIE, nóminas, contrato de trabalho, declaração de renda, aval, fianza + first month.

### Could (later)
- "Ask Claude" box (sentence → filters, on Claude Sonnet 5.5, via a logged-in-only Supabase Edge Function), with daily Claude tagging of richer features (sea view, natural light, quiet…).

### Should (later)
- Visit tracking (contacted → visit booked → visited → applied).
- Price per m² compared with the area average.
- Facebook groups and local agency websites as sources.

### Won't
- Buying or holiday rentals; any account system beyond the 2 users; automated contact of agents.

## Open questions
1. ~~Must-have features~~ Resolved: a flat needs a lift **or** A/C; a house needs A/C.
2. ~~Commute address~~ Resolved: work address, kept in the `COMMUTE_ADDRESS` secret (not in the repo).
3. **Partner's email** for the login whitelist.
4. ~~Blocked portals~~ Resolved: read saved-search alert emails from a dedicated Gmail over IMAP. These listings have no feature data and are labelled "check features".

## Compliance notes
Personal two-user tool, not opened to the public, so the global Privacy/Terms and account-deletion requirements don't apply. If that ever changes, revisit this.
