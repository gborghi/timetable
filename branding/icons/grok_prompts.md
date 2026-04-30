# Grok prompts: icons piTantum

Icone applicative del progetto. Tre target principali: favicon
(visibile a 16x16), apple-touch-icon (visibile a 180x180), PWA
icon-192/512.

A piccola scala l'alloro non e' leggibile -- privilegiare $\pi$ +
clessidra.

## Prompt 1: Favicon -> favicon.png (32x32)

```
Tiny app icon, must remain recognisable at 16x16. Lowercase Greek
letter pi rendered in warm gold (#c9a23a) on a deep indigo
(#1e3a5f) rounded square (corner radius about 12% of side).
Inside the two vertical strokes of pi, a minimal hourglass shape
in ivory (#f7f1de) -- just two stacked triangles meeting in the
center. NO laurel, NO text, no shadows.
Format: 32x32 PNG.
Style: bold, instantly recognisable, mobile/favicon use.
```

Dimensioni richieste: **32x32 PNG** (valida anche fino a 16x16).

---

## Prompt 2: Apple touch icon -> apple-touch-icon.png (180x180)

```
iOS / Android home-screen icon. Same monogram as the favicon (pi
with embedded hourglass) but with more detail: thin laurel sprigs
on either side of the pi (no full wreath -- just two short
laurel branches at 8-o'clock and 4-o'clock positions). Background:
deep indigo (#1e3a5f) rounded square (corner radius 22.5% of side
for iOS conformance). Pi in warm gold (#c9a23a). Hourglass in
ivory (#f7f1de) with gold sand. Laurel in muted gold (#c9a23a at
60% opacity).
Format: 180x180 PNG, NOT transparent.
Style: classical, premium, suitable for an educational app.
```

Dimensioni richieste: **180x180 PNG**.

---

## Prompt 3: PWA icon (maskable) -> icon-512.png + icon-192.png

```
Maskable PWA icon, 512x512 PNG. The icon must have a SAFE ZONE in
the center: 80% of the canvas (centered) is the actual logo,
the outer 10% on each side is the bleed area that the device
mask may crop. Repeat the favicon-style monogram (pi + hourglass)
filling the safe zone, with thin laurel sprigs at 8 and 4 o'clock.
Background: solid deep indigo (#1e3a5f) reaching to the edge.
Pi in warm gold (#c9a23a). Hourglass in ivory (#f7f1de) with gold
sand.
Format: 512x512 PNG.
Style: classical, designed for Android adaptive masks.
```

Dimensioni richieste: **512x512 PNG**, salva anche una versione
**192x192 PNG** scalando.

---

## Prompt 4: ICO multi-size -> favicon.ico

Solo se vuoi un .ico classico:

```
Multi-resolution Windows ICO file, sizes 16, 32, 48. Same monogram
as favicon.png (pi + hourglass on rounded indigo background, gold
and ivory). Each size optimised separately: at 16 the hourglass
becomes just a vertical line of dots between the pi strokes, at 48
the hourglass is fully visible.
```

Dimensioni richieste: **.ico multi-size** (16, 32, 48).

---

## File esistenti

In questa cartella ship-pa gia' `favicon.svg` (placeholder
funzionale, gia' wirato in `webui/frontend/src/app.html`). I browser
moderni supportano SVG come favicon, quindi finche' non carichi i PNG
il sito ha gia' un'icona.
