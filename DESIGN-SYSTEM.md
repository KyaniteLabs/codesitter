# DESIGN-SYSTEM.md — flawrite (the code review bot)

**Status:** approved (CEO-directed, evidence-based) · **Date:** 2026-08-31

## Direction

> **Fluorescent mineral sharpness** — a crystalline identity that reveals hidden flaws under UV light. Deep blue-purple base (fluorite's natural color), sharp geometric cuts (crystal faces), one luminous accent (the UV fluorescence). The bot is a crystal formation that watches code and glows when it finds something.

## Decision map

| Dimension | Decision | Evidence | Status |
|---|---|---|---|
| **reference** | Fluorite crystal specimens — banded purple/blue/green, geometric cleavage, UV fluorescence | The mineral IS the metaphor: reveals hidden structure under the right light | committed |
| **personality** | **Sharp but warm** — the competent reviewer who's seen everything but still says "thanks for this PR" | Tone presets: balanced (warm) → roast (savage); fork-override proves the warmth is real | committed |
| **aesthetic** | **Geometric crystal, dark-first** — angular shapes on deep backgrounds, luminous accents that "fluoresce" | GitHub is dark-mode-first; the bot must stand out without clashing; fluorite fluoresces | committed |
| **type** | Monospace-first (it's a code tool), with a display font for the brand mark only. No body-font decisions (comments are markdown, rendered by GitHub) | Primary surface = GitHub markdown; only the avatar and future landing page need type | committed |
| **color_mode** | **Dark-first** with light-mode compatibility. Dominant: deep indigo (#2C2C54). Accent: UV-luminous violet (#B892FF). Signal: warm amber for warnings (#F5A623). | Fluorite: deep purple base with UV-fluorescent purple/violet glow. GitHub dark mode is the primary context. | committed |
| **density_shape** | Low density (breathing room), sharp angular corners (4px max radius), no elevation/depth — flat crystal faces, not soft UI | Crystal = angular, flat, faceted. Not soft/rounded (that's a different mineral family). | committed |
| **structure_rhythm** | Header (severity table) → findings (numbered, one per section) → footer (brand). The rhythm is: summary → detail → sign-off. Scannable in 3 seconds. | Already implemented in the renderer; works on real PRs | committed |
| **signature** | **The UV glow** — one luminous accent color that appears only when a flaw is found (the "fluorescence"). On clean PRs, the bot is quiet and dark. On dirty PRs, it glows. | Fluorite literally does this — invisible under normal light, vivid under UV. Clean PRs get ✨, dirty PRs get glowing findings. | committed |
| **imagery_iconography** | Crystal/mineral iconography. The avatar IS a crystal. Severity emojis are colored circles (🔴🟠🟡🔵) matching mineral hardness-scale colors. No stock icons, no generic bot imagery. | Already using emoji severity badges that match the mineral color palette | committed |

## Refusals

1. **No rounded/cute UI shapes** — crystals are angular; this is not a toy.
2. **No gradient backgrounds** — crystals have distinct bands, not smooth gradients.
3. **No anthropomorphic robot imagery** — no robot faces, no gears, no "AI" visual clichés.
4. **No red/green Christmas palette** — severity colors are warm/cool spectrum, not traffic lights.
5. **No "powered by AI" badges** — the org law is the power source, not a marketing badge.

## Semantic tokens

```css
/* flawrite design tokens */
--flawrite-base: #2C2C54;        /* deep indigo — fluorite's primary band */
--flawrite-base-deep: #1A1A2E;   /* near-black indigo — the depth */
--flawrite-accent: #B892FF;      /* UV violet — the fluorescence */
--flawrite-accent-glow: #D4B5FF; /* lighter violet — the glow effect */
--flawrite-signal-warm: #F5A623; /* amber — warnings, Minor severity */
--flawrite-signal-cool: #4A90D9; /* blue — Nit severity, informational */
--flawrite-critical: #E85D5D;    /* warm red — Critical severity */
--flawrite-major: #F0A030;       /* orange — Major severity */
--flawrite-success: #5DBB63;     /* green — clean PR, no findings */

--flawrite-radius: 4px;          /* angular — crystal face */
--flawrite-radius-sm: 2px;       /* sharp edge */
--flawrite-font-display: 'Space Grotesk', sans-serif;  /* if we ever need one */
--flawrite-font-mono: 'JetBrains Mono', monospace;     /* code contexts */
```

## Avatar generation prompt (Grok-optimized)

Based on the design system above, here's the image prompt following best practices (subject, style, colors, composition, mood, format):

```
A geometric crystal formation avatar, designed as a mascot for a code review bot called "flawrite". The crystal is angular and faceted like a fluorite specimen — deep indigo purple (#2C2C54) with sharp geometric planes. One facet glows with luminous violet light (#B892FF) as if fluorescing under UV, revealing an eye-like inclusion within the crystal — watchful, alert, slightly opinionated. The crystal has a subtle intelligence to it, not cute or cartoonish but sophisticated and sharp. Clean vector-style illustration, flat colors with sharp edges, no gradients or soft shading. Square composition centered on the crystal against a solid deep dark background (#1A1A2E). The glowing violet eye is the focal point — it's looking at code, spotting a flaw. Modern, minimal, memorable. No text, no watermark, no robot clichés. Style: clean vector art, mineral specimen aesthetic, dark-mode friendly.
```

## Next move

1. Run the Grok prompt above to generate the avatar
2. Upload to `github.com/settings/apps/kyanitelabs` (one click)
3. Rename the product to the final name (CEO pick: flawrite / flawr1te / fl4write)
4. The next implementation step after that: a landing page using these tokens
