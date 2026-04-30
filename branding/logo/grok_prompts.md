# Grok prompts: logo piTantum

Prompt copia-incolla per generare i loghi del progetto. Tre elementi
ricorrenti: lettera greca $\pi$ minuscola, clessidra, alloro.
Palette: indaco profondo `#1e3a5f`, oro caldo `#c9a23a`, terra di Siena
`#9c4a1c`, avorio `#f7f1de`.

Salva i file generati in questa cartella con i nomi indicati e
copia anche la versione "served" in
`webui/frontend/static/branding/logo/`.

---

## Prompt 1: Logo principale (light variant) -> logo_light.png

```
Minimalist classical-modern logo featuring a stylized lowercase Greek
letter pi (the symbol pi as in mathematics, with two vertical strokes
and a horizontal bar on top) in elegant serif typography. Inside the
two vertical strokes of the pi, embed a slim hourglass with sand
falling, drawn in fine line work. The pi is encircled by a delicate
laurel wreath made of two symmetric branches meeting at the bottom.
Color palette: deep indigo blue (#1e3a5f) for the pi and laurel
outlines, warm gold (#c9a23a) for the hourglass sand and laurel
fills, ivory (#f7f1de) negative space.
Format: 512x512 PNG with transparent background.
Style: classical Roman elegance, suitable for educational software.
No text, no shadows, vector-clean lines.
```

Dimensioni richieste: **512x512 PNG trasparente**.

---

## Prompt 2: Logo principale (dark variant) -> logo_dark.png

```
Same minimalist classical-modern logo as light variant: lowercase
Greek letter pi with an hourglass embedded between its two vertical
strokes, encircled by a laurel wreath. Colors adapted for dark
backgrounds: light indigo (#88a5d8) for the pi and laurel outlines,
soft gold (#f0c869) for the hourglass sand. Ivory accents (#f7f1de)
for highlights. Background fully transparent.
Format: 512x512 PNG transparent.
Style: classical Roman elegance, no text, vector-clean lines.
```

Dimensioni richieste: **512x512 PNG trasparente**.

---

## Prompt 3: Wordmark orizzontale -> logo_horizontal.png

```
Horizontal logo lockup: on the left, the small classical pi-with-
hourglass-and-laurel mark from the main logo (about 200x200 area).
On the right, the wordmark "piTantum" rendered as an elegant serif
in deep indigo (#1e3a5f), where the leading 'pi' is the lowercase
Greek letter (pi) drawn in warm gold (#c9a23a), italicized, and the
remaining "Tantum" is upright Roman serif in indigo. Below the
wordmark, in small italic gray (#5a6477), the latin epigraph
"Omnia, Lucili, aliena sunt, tempus tantum nostrum est." in 11pt.
Format: 1200x300 PNG transparent background.
Style: classical Roman elegance, generous letter spacing.
```

Dimensioni richieste: **1200x300 PNG trasparente**.

---

## Prompt 4: Variante minimal per favicon -> logo_mark.png

```
Minimal monogram suitable as a favicon at small sizes (down to 16x16
visibility). Lowercase Greek letter pi in warm gold (#c9a23a) on a
solid deep indigo (#1e3a5f) circular field. Inside the two vertical
strokes of pi, a tiny hourglass shape (just two stacked triangles)
in ivory (#f7f1de). NO laurel (too detailed for small sizes).
NO text. The pi mark dominates the canvas (60% of width).
Format: 512x512 PNG, solid square or circular background, NOT
transparent.
Style: bold, instantly recognisable, mobile/favicon use.
```

Dimensioni richieste: **512x512 PNG**.

---

## Note di consistenza

- Il logo principale (Prompt 1 e 2) deve restare leggibile a 64x64.
- I tratti verticali della $\pi$ sono il "punto di forza" del marchio:
  contengono la clessidra. Ogni variante deve preservare questo
  dettaglio o (per il marchio favicon, Prompt 4) ridurlo a una forma
  schematica.
- L'alloro non e' negoziabile nei loghi grandi (Prompt 1, 2, 3) -- il
  riferimento classico a Seneca e' centrale al brand. Sfrondare solo
  per il favicon (Prompt 4).
- Niente shadow / 3D / glow: lo stile e' incisione classica /
  design editoriale, non illustrazione moderna.

## File esistenti nel repo

In questa cartella ci sono gi\`a `logo_light.svg` (placeholder
generato col tema corretto). Quando carichi il PNG di Grok, mantieni
sia il PNG (master) sia rinomina l'SVG in `logo_light_placeholder.svg`
oppure rimuovilo se preferisci.
