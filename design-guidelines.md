# Design Guidelines — Casa Almería (rental finder)

## Archetype
**B. Warm Indie Craft, kept quiet.** You both arrive hopeful, picturing a life somewhere, so the page should feel like a shared notebook with photos tucked in, not a control panel. The quietness (no chrome, fast, nothing competing for attention) is borrowed as *behaviour* from Things 3 and Linear, not as their visual style. Photos carry the colour; the interface steps back.

Physical object: a linen notebook you both scribble in.
References: Things 3, Fathom, Pirsch, Hey.

## Design Tokens
Stack: Vite + TypeScript + Tailwind (no shadcn). Tokens are CSS variables in `web/src/styles.css`, exposed to Tailwind via `@theme`.

```css
:root {
  /* Surfaces: warm paper, never pure white for the page */
  --bg:              #faf8f5;  /* page: warm off-white, letterpress paper */
  --surface:         #f2ede6;  /* filter sheet, chips at rest */
  --raised:          #ffffff;  /* cards: white so photos read true-colour */
  --border:          rgba(28, 25, 23, 0.08);
  --border-strong:   rgba(28, 25, 23, 0.16);

  /* Text: warm stone, contrast-checked on --bg */
  --text:            #1c1917;  /* 16.5:1 */
  --text-2:          #57534e;  /* 7.2:1, metadata line */
  --text-3:          #78716c;  /* 4.5:1, timestamps (template #a8a29e failed at 2.4:1) */

  /* One accent: almagra, the iron-oxide red of Almería's earth and pottery */
  --accent:          #b4431c;  /* 5.3:1 on bg; white on it 5.6:1. Actions, "novo", ❤️ */
  --accent-hover:    #8f3516;
  --accent-muted:    rgba(180, 67, 28, 0.08);  /* liked-card tint, active chip bg */
  --on-accent:       #ffffff;  /* text on accent buttons; becomes dark in dark mode (white on dark accent was 3.0:1) */

  /* Semantic, never decorative */
  --positive:        #15803d;  /* 4.7:1, price dropped */
  --warning:         #92400e;  /* 6.7:1, "confirmar extras" (features unknown) */

  /* Radius: three values only, larger on cards than controls */
  --r-sm: 6px;   /* chips, buttons */
  --r-md: 10px;  /* inputs, sheet */
  --r-lg: 16px;  /* cards, photos */

  /* Shadow: two levels */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 1px 3px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04);

  /* Type */
  --font-display: "Fraunces", Georgia, serif;  /* prices + place names only */
  --font-ui: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1c1917; --surface: #292524; --raised: #322d2a;
    --border: rgba(255,255,255,0.08); --border-strong: rgba(255,255,255,0.16);
    --text: #ece8e4; --text-2: #c9c3bd; --text-3: #a39b94;
    --accent: #e6855f; --accent-hover: #ee9d7d; --accent-muted: rgba(230,133,95,0.12); --on-accent: #1c1917;
    --positive: #4ade80; --warning: #fbbf24;
  }
}
```

**Type scale** (1.25 ratio, 5 sizes): 12 (meta, badges) · 14 (UI, chips) · 16 (body, notes) · 20 (card price) · 25 (page title). Prices use `font-variant-numeric: tabular-nums`. Weights 400 / 500 / 600 only.

**Spacing**: 8px grid. Card padding 16px on mobile, gap between cards 12px. Label-to-value 4px. Sections 32px.

## Design Principles
1. **The photo is the card.** A 4:3 photo takes the top of every card. Everything else is one line of facts under it.
2. **Price and the catch first.** Each card's first text line is price and bedrooms/m²; the second says what's missing ("sem elevador", "confirmar extras"). That's how you'd text it.
3. **Almagra means "act or new".** The accent is only for ❤️, the "novo" dot and the primary button. Never on borders or decoration.
4. **Serif only for prices and place names.** Fraunces gives warmth where you linger. All UI text is the system font, which is fast on phones and needs no download.
5. **One screen, three views.** Novos / Todos / Favoritos. No sidebar, no settings page. Filters live in a bottom sheet.
6. **Shared by default.** Every ❤️, ❌ and note shows whose it is (initials). Nothing is private between the two of you.
7. **Honest about gaps.** Listings from email alerts say "confirmar extras". A blocked source says so in the footer. The page never pretends to know.
8. **Thumb-first.** Reactions sit at the bottom-right of each card, with 44px touch targets.

## Copy Voice
Voice: **the two of you texting about flats.** PT-PT, informal "tu" everywhere, never "você"/"o seu".

Attributes:
- **Numbers before adjectives.** "850 € · 3 quartos · 95 m²", not "Amplo e luminoso".
- **States the catch plainly.** "Sem elevador. 4º andar.", not "Edifício sem elevador".
- **Short, like a message.** Max ~12 words per line. Fragments are fine.
- **Names the person.** "{Nome} gostou", not "Marcado como favorito".
- **One light touch of humour, never in errors.**

Banned: the universal list, plus "imóvel de sonho", "oportunidade única", "não perca", "fantástico", "espetacular" (portal-speak), "com sucesso", "Ups", exclamation marks on errors.

## Microcopy (PT-PT)
1. Primary button: **"Enviar link de entrada"**
2. Secondary button: **"Abrir anúncio"**
3. Empty, Novos: **"Nada de novo desde ontem. Os portais voltam a ser lidos amanhã de manhã."**
4. Empty, Favoritos: **"Ainda sem favoritos. Carrega no ❤️ e fica aqui para os dois."**
5. User error, login: **"Esse email não está na lista. Usa o email que combinámos."**
6. System error: **"Não consegui carregar os anúncios. Falhou a ligação ao servidor. Tenta outra vez daqui a um minuto."**
7. Loading: **"A juntar os anúncios…"**
8. Success, login: **"Link enviado para {email}. Abre-o neste telemóvel."**
9. Destructive confirm: **"Apagar a tua nota sobre “{título}”? {Nome} também deixa de a ver."** Buttons: "Apagar nota" / "Manter"
10. Tooltip, "confirmar extras": **"Veio de um alerta por email: não sabemos se tem elevador ou ar condicionado. Vê no anúncio."**

## IA / Flow
Single page, one column on phones; 2–3 card columns from 720px; list + map side by side from 1100px.

```
[Casa Almería]                       [Lista | Mapa]
[Novos 12] [Todos 318] [Favoritos 4]           ← the only navigation
[Filtros (3)]  chips: ≤900 €  ·  Zapillo  ·  Mobilado
──────────────────────────────────────────────
Card: photo carousel (swipe) · "novo" dot · sources ("pisos · fotocasa")
      850 €  ·  3 quartos · 95 m²            (serif price)
      Zapillo, Almería · há 2 dias
      chips: elevador  ar cond.  terraço  mobilado      | "confirmar extras"
      "baixou 50 €" (green) when applicable
      [❤️ AB] [❌]  [nota…]                    [Abrir anúncio →]
──────────────────────────────────────────────
Footer: Fontes: pisos ✓ · enalquiler ✓ · fotocasa ✓ ontem · idealista: sem alertas
```

- **Novos** = first seen since your last visit (stored per user). Default view.
- **Todos** hides ❌ unless the filter "mostrar descartados" is on.
- **Sort**: Novos by newest; Todos furnished first, then commute (when available), then newest.
- **Flows**: (1) First visit: email → magic link → Novos. (2) Daily: open → Novos → ❤️/❌/nota → open listing. (3) Recovery: expired link → "Enviar link de entrada" again; source down → footer chip says since when.

## Non-negotiables
- UI language PT-PT, "tu" form. Listing text stays as the portal wrote it (Spanish).
- WCAG 2.2 AA: all text pairs above are checked; touch targets 44px.
- Light-first; dark derived through `prefers-color-scheme`.
- No dark crypto/tech look.
