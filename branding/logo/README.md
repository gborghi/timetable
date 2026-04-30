# branding/logo/

Loghi principali del progetto Carpe Diem.

## File attesi

| File                 | Tipo            | Dimensioni minime  | Note |
| -------------------- | --------------- | ------------------ | ---- |
| `logo_light.png`     | PNG trasparente | 512x512            | logo per sfondi chiari, usato dall'header del frontend (`/branding/logo/logo_light.png`) |
| `logo_dark.png`      | PNG trasparente | 512x512            | variante per dark mode (futuro) |
| `logo_wordmark.png`  | PNG trasparente | 800x200            | solo wordmark "Carpe Diem", senza icona |
| `logo_square.png`    | PNG             | 512x512            | versione squadrata con sfondo solido (per favicon e social) |
| `logo_horizontal.png`| PNG trasparente | 1200x300           | versione orizzontale (icona a sinistra, wordmark a destra) |
| `logo.svg`           | SVG             | -                  | versione vettoriale per export print / scalabilita' |

## Idee per il design

- Il latino "Carpe diem" e' stato adottato come tagline; il logo dovrebbe
  evocare l'idea di "afferrare il momento": metafore visive possibili
  sono una clessidra, un sole nascente, una mano che chiude su una
  spiga (riferimento al "carpere" = cogliere, raccogliere, anche le
  spighe).
- La componente "scolastica" puo' essere rendered con un griglia
  6x6 stilizzata (la matrice oraria e' la cifra grafica costante della
  UI).
- Tone: classico ma moderno; non corsivo decorativo, ma neanche
  flat-design freddo.

## Wire frontend

Il file `logo_light.png` viene letto da
`webui/frontend/src/routes/+layout.svelte` come immagine dell'header
(`<img src="/branding/logo/logo_light.png" .../>`). Se manca, l'UI
mostra il wordmark "Carpe Diem" in puro testo.
