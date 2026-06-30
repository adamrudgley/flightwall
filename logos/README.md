# Airline Logos

Drop small PNG icons here, named by the airline's 3-letter ICAO code
(this is what shows in the first 3 letters of a callsign, e.g. QFA15 -> QFA).

## Common airlines you'll see over Camp Hill

| Code | Airline           | Filename     |
|------|--------------------|--------------|
| QFA  | Qantas             | QFA.png      |
| JST  | Jetstar            | JST.png      |
| VOZ  | Virgin Australia   | VOZ.png      |
| QLK  | QantasLink         | QLK.png      |
| UAE  | Emirates           | UAE.png      |
| ANZ  | Air New Zealand    | ANZ.png      |
| CAL  | China Airlines     | CAL.png      |
| SIA  | Singapore Airlines | SIA.png      |
| CPA  | Cathay Pacific     | CPA.png      |
| RSCU | Rescue helicopters | RSCU.png     |

## Specs

- **Size**: 16x16 to 24x24 pixels works best (will be auto-resized to 20x20)
- **Format**: PNG with transparent background (so it sits nicely on black)
- **Style**: Simple, bold shapes read best at this resolution — a kangaroo
  silhouette, a tail logo, or just the airline's brand colour as a solid
  circle with 2-3 letters works better than a detailed logo

## Where to find/make them

- Many airlines publish small favicon-style logos on their websites you can
  screenshot and crop down to a square
- Use any image editor (Preview on Mac, GIMP, even Photoshop) to crop to a
  square and resize down to ~20x20px, save as PNG with transparency
- For Qantas, the simplest approach is just the red kangaroo silhouette
  cropped to a square

## If a logo is missing

No problem — flightwall.py automatically generates a coloured circular
"monogram" badge using the airline's initials if no PNG is found, so the
display always looks complete even without a logo file.
