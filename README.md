# Typography sculpture — ESADSE, Atelier Graphisme

A topographic relief of the history of Latin typography, built as a 1:1 cardboard prototype (95 × 50 × 30 cm) for the Atelier Graphisme at the École supérieure d'art et design de Saint-Étienne.

- **Height = time.** Five equal discs of 19 cm: Antiquity, early Common Era, Middle Ages, early modern, contemporary.
- **Width × depth = a faithful world map** (Miller projection, west–east on 50 cm). Each layer covers the places where a typographic period lived at that date.
- **Critique built into the form.** The whole European story, from Gutenberg to the Bauhaus, fits in about 6 × 4 cm of the map; most of the world receives no layer because the source book (*Typo*, Friedl, Ott & Stein) does not mention it.

**Viewer:** https://saviotp.github.io/esadse-graphisme-typography-sculpture/

## How it is built

The data (periods and places) lives in a note of the author's Obsidian vault, not here. `generator/build.py` reads that note, projects Natural Earth borders (public domain), slices the tower into cardboard layers (5 mm or 3 mm) and writes:

| Output | What |
| --- | --- |
| `data/territoires.csv` | the table read from the note (derived, never edited by hand) |
| `docs/` | the interactive 3D viewer (three.js) and its layer data |
| `out/plates/` | 1:1 technical sheets: plan of each disc, front and right elevations, layer table |

```sh
python3 -m venv .venv && .venv/bin/pip install shapely
mkdir -p data/cache
curl -L -o data/cache/countries.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
curl -L -o data/cache/land.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
.venv/bin/python generator/build.py "<path to the vault note>.md"
```

Laser cut files come in a later round, once the prototype is validated against the notes.
