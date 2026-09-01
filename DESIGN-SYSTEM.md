# DESIGN-SYSTEM.md — Fl4wRite (the code review bot)

**Status:** approved · **Date:** 2026-08-31 · **Version:** 2 (Pokemon direction)

## Direction

> **16-bit crystal Pokemon** — a cute, chunky, translucent fluorite creature with big glowing eyes that spot problems in your code. Vibrant green-purple banded crystal body, friendly-judgmental expression, retro SNES-era sprite aesthetic.

## Decision map

| Dimension | Decision | Status |
|---|---|---|
| **reference** | Fluorite crystal + 16-bit Pokemon sprites (Geodude, Sableye, Crystal Onix energy) | committed |
| **personality** | Cute but judgmental — big curious eyes that narrow when they spot a flaw | committed |
| **aesthetic** | 16-bit pixel art, dark background, chunky sprite, saturated retro colors | committed |
| **type** | N/A (primary surface is GitHub markdown; avatar is pixel art) | committed |
| **color_mode** | Dark bg + vibrant fluorite bands: purple (#7B2D8E), green (#2E8B57), glowing eyes (#E8E0FF) | committed |
| **density_shape** | Chunky, geometric, faceted — visible pixels, clean outlines | committed |
| **structure_rhythm** | Severity table header → findings as sections → footer | committed |
| **signature** | The glowing eyes — they light up when they spot a problem | committed |
| **imagery_iconography** | 16-bit pixel art crystal creature; severity emojis (🔴🟠🟡🔵) in text | committed |

## Refusals

1. No corporate/minimal/vector aesthetics
2. No illuminati/sacred geometry/concentric rings
3. No robot imagery
4. No dark indigo + UV violet tech-slop
5. No "powered by AI" badges

## Tokens

```css
--flx-bg: #0A0A12;
--flx-crystal-purple: #7B2D8E;
--flx-crystal-green: #2E8B57;
--flx-eye-glow: #E8E0FF;
--flx-sparkle: #FFFFFF;
--flx-severity-critical: #E85D5D;
--flx-severity-major: #F0A030;
--flx-severity-minor: #F5D623;
--flx-severity-nit: #4A90D9;
--flx-severity-clean: #5DBB63;
```
