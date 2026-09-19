# CC Brain Website Design Spec

## Overview

Minimal landing page for CC Brain — a macOS menu bar app that watches Claude Code sessions and generates living Markdown summaries. The site has two sections: a full-bleed hero with an interactive dithered wave background and a simple footer.

Target audience: developers using Claude Code who are frustrated by losing context across sessions.

## Stack

- **Framework:** React + TypeScript + Vite
- **Tooling:** bun (scaffold, install, dev, build)
- **Styling:** Tailwind CSS
- **Hosting:** Cloudflare Pages
- **Location:** `website/` subdirectory of the cc-brain repo

## Dependencies

| Package | Purpose |
|---------|---------|
| `three` | 3D rendering for Dither component |
| `postprocessing` | Post-processing effects |
| `@react-three/fiber` | React renderer for Three.js |
| `@react-three/postprocessing` | R3F postprocessing bindings |
| `motion` | Animation library for BlurText component |
| `@fontsource/jetbrains-mono` | Self-hosted JetBrains Mono font (400, 500, 700) |

## Components

### Dither (from React Bits)

Full-viewport Three.js canvas rendering a dithered wave pattern with Bayer matrix post-processing.

**Source:** Copied into `src/components/Dither.tsx` (+ `Dither.css`)

**Props used:**
- `waveColor`: animated from `[0, 0, 0]` to `[0.49, 0.56, 0.66]` (silver-blue)
- `colorNum`: 25
- `waveAmplitude`: 0.32
- `waveFrequency`: 3
- `waveSpeed`: 0.07
- `enableMouseInteraction`: true
- `mouseRadius`: 0.2

### BlurText (from React Bits)

Word-by-word blur/fade text reveal animation using Framer Motion.

**Source:** Copied into `src/components/BlurText.tsx`

**Usage:**
- Headline: `animateBy="words"`, `direction="bottom"`, `delay=100`
- Subline: same config, triggered after headline completes via `onAnimationComplete`

## Layout

```
┌──────────────────────────────────────────┐
│  HERO (100vh, position: relative)        │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │  Dither canvas (absolute, fill)  │    │
│  └──────────────────────────────────┘    │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │  Content (z-10, flex center)     │    │
│  │                                  │    │
│  │  [brain-fill.svg] CC Brain       │    │  ← top-left, absolute
│  │                                  │    │
│  │  "Your context window            │    │  ← BlurText, text-4xl/6xl
│  │   has amnesia."                  │    │
│  │                                  │    │
│  │  "CC Brain watches your..."      │    │  ← BlurText, text-lg
│  │                                  │    │
│  │  ┌────────────────────────┐      │    │
│  │  │ $ curl ... | bash [📋]│      │    │  ← monospace, copy button
│  │  └────────────────────────┘      │    │
│  │                                  │    │
│  │  ★ Star on GitHub · MIT          │    │  ← links
│  └──────────────────────────────────┘    │
│                                          │
├──────────────────────────────────────────┤
│  FOOTER                                  │
│  MIT · GitHub · basheer421               │  ← muted, single line
└──────────────────────────────────────────┘
```

## Content

**Logo:** `icons/brain-fill.svg` rendered inline as a React component, white, ~24px. Placed top-left with "CC Brain" text beside it.

**Headline:** "Your context window has amnesia."

**Subline:** "CC Brain watches your Claude Code sessions and writes living summaries. Next session picks up where you left off."

**Install command:**
```
curl -sSL cc-brain.bachir.me | bash
```
Displayed in a monospace code block with a copy-to-clipboard button. On click, copies the command and shows brief "Copied!" feedback.

**Links below install:**
- "Star on GitHub" → `https://github.com/basheer421/cc-brain`
- "MIT Licensed" (text only, no link needed)

**Footer:**
```
MIT · GitHub · basheer421
```
GitHub links to the repo. "basheer421" links to `https://github.com/basheer421`.

## Animation Sequence

1. **T=0:** Page loads. Dither canvas renders with `waveColor=[0,0,0]` (invisible against black).
2. **T=0 → T=2s:** `waveColor` lerps from `[0,0,0]` to `[0.49,0.56,0.66]` via `requestAnimationFrame`. The dithered wave pattern gradually emerges.
3. **T=0.5s:** BlurText headline begins animating — words blur/fade in from bottom.
4. **On headline complete:** BlurText subline begins animating.
5. **On subline complete:** Install command box and links fade in via CSS transition (`opacity 0→1`, `transform translateY(10px)→0`, ~0.5s).

The color lerp is implemented in the parent component using `useState` for `waveColor` and a `useEffect` with `requestAnimationFrame` that interpolates each RGB channel linearly over the duration.

## Typography

**Font:** JetBrains Mono throughout (mono-forward, matches dither aesthetic). Self-hosted via `@fontsource/jetbrains-mono` — no CDN dependency.

- Headline: `text-4xl md:text-6xl font-bold tracking-tight`
- Subline: `text-base md:text-lg font-normal text-white/70`, max-width ~600px
- Logo "CC Brain": `text-sm font-medium tracking-widest uppercase`
- Install command: JetBrains Mono (same font, differentiated by container styling)
- Footer: `text-xs text-gray-500`
- All hero text: white

## Responsive

- Hero content centered on all viewports
- Headline scales down via Tailwind responsive prefixes
- Install command box: full-width on mobile with horizontal scroll if needed
- Dither canvas: always fills viewport (Canvas `dpr={1}` keeps perf acceptable on mobile)

## File Structure

```
website/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.css            (Tailwind directives)
│   ├── components/
│   │   ├── Dither.tsx
│   │   ├── Dither.css
│   │   ├── BlurText.tsx
│   │   ├── Hero.tsx          (hero section, orchestrates animations)
│   │   ├── InstallCommand.tsx (code block + copy button)
│   │   └── Footer.tsx
│   └── assets/
│       └── brain-fill.svg
└── public/
    └── (favicon, etc.)
```

## Deployment

Cloudflare Pages, building from the `website/` subdirectory.

- Build command: `cd website && bun install && bun run build`
- Output directory: `website/dist`
- No server-side rendering — pure static SPA

## Tone

Dry, technical humor. Dev-to-dev. No exclamation marks, no marketing superlatives, no "supercharge your workflow." The product solves a real annoyance; state it plainly.
