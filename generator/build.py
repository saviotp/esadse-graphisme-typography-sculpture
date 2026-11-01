"""Gera a geometria da escultura a partir da nota da vault.

Uso:  .venv/bin/python generator/build.py "<caminho da nota .md>"

Saídas: data/territoires.csv, docs/layers-<t>.json, out/plates/*.svg, out/plates/layers-<t>.csv
"""
import csv, hashlib, json, math, re, sys
from pathlib import Path

from shapely import ops
from shapely.geometry import Point, Polygon, MultiPolygon, box, shape, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
NOTE = Path(sys.argv[1])

# --- Volume (nota § Volume e § Forme) -------------------------------------
W, D, H = 500.0, 300.0, 950.0          # mm: oeste–leste, norte–sul, altura
DISCS = [(-3000, 0, "Antiquité"), (0, 500, "Début de l'ère commune"), (500, 1450, "Moyen Âge"),
         (1450, 1914, "Époque moderne"), (1914, 2026, "Contemporaine")]
DISC_H = H / len(DISCS)                 # 190 mm
THICKNESSES = [5.0, 3.0]
CITY_D = 8.0                            # diâmetro do círculo de cidade (mm)
REGION_PAD = 1.5                        # engrossa regiões finas (vale do Nilo)
SIMPLIFY = 0.25                         # mm
MIN_AREA = 2.0                          # mm² — fragmentos menores são descartados

# --- Projeção de Miller, mundo inteiro em 500 mm --------------------------
K = W / (2 * math.pi)
def miller(lat): return 1.25 * math.log(math.tan(math.pi / 4 + 0.4 * math.radians(max(min(lat, 89.9), -89.9))))
YN = miller(89.9)
def proj(lon, lat): return ((math.radians(lon) + math.pi) * K, (YN - miller(lat)) * K)
def proj_geom(g): return ops.transform(lambda xs, ys, zs=None: tuple(zip(*[proj(x, y) for x, y in zip(xs, ys)])), g)
BOX = box(0, 0, W, D)

# --- Lugares ---------------------------------------------------------------
PAYS = {"Turquie": "Turkey", "Chine": "China", "Syrie": "Syria", "Liban": "Lebanon", "Israël": "Israel",
        "Grèce": "Greece", "Italie": "Italy", "Espagne": "Spain", "Allemagne": "Germany", "France": "France",
        "Pays-Bas": "Netherlands", "Royaume-Uni": "United Kingdom", "États-Unis": "United States of America",
        "Hongrie": "Hungary", "Pologne": "Poland", "Suisse": "Switzerland", "Japon": "Japan"}
LISTES = {  # régions = listes de pays (estimation)
    "Europe": ["France", "Germany", "Italy", "Spain", "Portugal", "United Kingdom", "Ireland", "Belgium",
               "Netherlands", "Luxembourg", "Switzerland", "Austria", "Czechia", "Poland", "Hungary", "Denmark"],
    "URSS": ["Russia", "Ukraine", "Belarus"],
    "Tchécoslovaquie": ["Czechia", "Slovakia"],
    "Yougoslavie": ["Republic of Serbia", "Croatia", "Slovenia", "Bosnia and Herzegovina", "Montenegro",
                    "North Macedonia", "Kosovo"],
    "Europe centrale": ["Austria", "Czechia", "Slovakia", "Hungary"],
}
POLY = {  # régions dessinées (lon, lat) — estimation
    "Mésopotamie": [(43.5, 36.0), (45.5, 35.0), (48.5, 31.0), (48.5, 29.8), (46.5, 29.8), (44.0, 31.2), (42.0, 34.0)],
    "Assyrie": [(41.5, 37.3), (44.5, 37.3), (45.2, 35.3), (43.0, 34.8), (41.5, 35.8)],
    "Vallée du Nil": [(29.6, 31.6), (32.6, 31.4), (31.6, 29.8), (31.6, 27.0), (33.2, 24.0), (32.6, 23.6), (30.6, 27.0), (30.8, 29.8)],
    "Empire romain": [(-9.5, 38.7), (-9.0, 43.5), (-1.5, 43.5), (-4.5, 48.5), (-5.8, 50.0), (-3.0, 55.0), (1.5, 53.0),
                      (4.0, 51.6), (6.5, 51.8), (7.5, 50.0), (10.0, 49.0), (13.0, 48.5), (17.0, 48.0), (19.0, 47.7),
                      (22.0, 48.2), (26.0, 48.3), (28.5, 45.5), (30.0, 46.5), (34.0, 45.3), (36.5, 45.5), (40.0, 43.0),
                      (44.0, 41.5), (46.0, 39.0), (44.5, 37.5), (47.0, 33.0), (48.0, 30.0), (44.0, 31.0), (40.0, 33.0),
                      (37.0, 31.0), (35.0, 28.0), (33.0, 29.5), (32.5, 23.0), (31.0, 23.0), (30.0, 29.5), (25.0, 31.5),
                      (20.0, 30.5), (15.0, 32.0), (11.0, 33.0), (10.0, 34.0), (8.5, 35.0), (4.0, 36.0), (0.0, 35.5),
                      (-5.0, 35.5), (-6.5, 34.0), (-9.0, 32.5), (-9.0, 34.0), (-6.0, 36.0), (-9.5, 37.0)],
}
VILLES = {"Ougarit": (35.78, 35.60), "Milet": (27.28, 37.53), "Bagdad": (44.36, 33.31), "Mayence": (8.27, 50.0),
          "Venise": (12.32, 45.44), "Londres": (-0.13, 51.51), "Zurich": (8.54, 47.37), "Berlin": (13.40, 52.52),
          "Paris": (2.35, 48.86), "New York": (-74.0, 40.71), "Bâle": (7.59, 47.56), "Los Angeles": (-118.24, 34.05),
          "Chicago": (-87.63, 41.88), "Milan": (9.19, 45.46)}
# partes de países longe do território principal (ultramar, Alasca, Chukotka) ficam de fora
BBOX = {"France": (-25, 34, 45, 72), "Netherlands": (-25, 34, 45, 72), "United Kingdom": (-25, 34, 45, 72),
        "Spain": (-25, 34, 45, 72), "Portugal": (-25, 34, 45, 72), "Denmark": (-25, 34, 45, 72),
        "United States of America": (-125, 24, -66, 50), "Russia": (0, 0, 180, 90)}


def load_world():
    cache = ROOT / "data" / "cache"
    countries = {}
    for f in json.load(open(cache / "countries.geojson"))["features"]:
        name = f["properties"]["ADMIN"]
        g = shape(f["geometry"])
        parts = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        if name in BBOX:
            x0, y0, x1, y1 = BBOX[name]
            parts = [p for p in parts if x0 <= p.centroid.x <= x1 and y0 <= p.centroid.y <= y1]
        countries[name] = proj_geom(unary_union(parts)).buffer(0)
    land = unary_union([proj_geom(shape(f["geometry"])).buffer(0)
                        for f in json.load(open(cache / "land.geojson"))["features"]]).intersection(BOX)
    return countries, land


def place_geom(name, kind, countries, land):
    if kind == "pays":
        return countries[PAYS[name]]
    if kind == "ville":
        return Point(*proj(*VILLES[name])).buffer(CITY_D / 2, 32)
    if name == "Monde":
        return land
    if name in LISTES:
        return unary_union([countries[c] for c in LISTES[name]])
    if name in POLY:
        p = proj_geom(Polygon(POLY[name]))
        return p.intersection(land).buffer(REGION_PAD).intersection(land)
    raise KeyError(f"lieu inconnu : {name} ({kind})")


# --- Leitura da nota ------------------------------------------------------
def num(s):
    s = s.strip().replace("−", "-").replace(" ", "").replace(" ", "")
    return int(s) if s else None

def section(text, title):
    m = re.search(rf"^## {re.escape(title)}.*?$(.*?)(?=^## )", text, re.M | re.S)
    if not m: raise SystemExit(f"seção não encontrada: {title}")
    return m.group(1)

def read_note():
    text = NOTE.read_text()
    periods = {}
    for line in section(text, "Chronologie (de ses notes)").splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\S+)\s*→\s*(\S+)\s*\|", line)
        if m:
            periods[int(m[1])] = {"n": int(m[1]), "name": m[2], "start": num(m[3]), "end": num(m[4])}
    rows = []
    for line in section(text, "Territoires — données du relief").splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) != 7 or not c[0].isdigit(): continue
        n = int(c[0]); p = periods[n]
        rows.append({"period": n, "place": c[1], "kind": c[2],
                     "start": num(c[3]) if c[3] else p["start"], "end": num(c[4]) if c[4] else p["end"],
                     "in_notes": c[5], "source": c[6]})
    return periods, rows


# --- Tempo ↔ altura -------------------------------------------------------
def z_to_date(z):
    i = min(int(z // DISC_H), len(DISCS) - 1)
    a, b, _ = DISCS[i]
    return a + (b - a) * (z - i * DISC_H) / DISC_H, i

def date_to_z(d):
    for i, (a, b, _) in enumerate(DISCS):
        if a <= d <= b:
            return i * DISC_H + (d - a) / (b - a) * DISC_H
    return 0.0 if d < DISCS[0][0] else H


def polys(g):
    if g.is_empty: return []
    gs = g.geoms if hasattr(g, "geoms") else [g]
    out = []
    for p in gs:
        if isinstance(p, Polygon) and p.area >= MIN_AREA: out.append(p)
        elif hasattr(p, "geoms"): out += polys(p)
    return out

def rings(p):
    r = lambda ring: [[round(x, 1), round(y, 1)] for x, y in list(ring.coords)[:-1]]
    return [r(p.exterior)] + [r(h) for h in p.interiors]


def build(t, periods, rows, geoms):
    n = int(round(H / t))
    shapes, shape_ids, layers, csv_rows = [], {}, [], []
    prev_union = None
    for i in range(n):
        z0, z1 = i * t, (i + 1) * t
        d0, disc = z_to_date(z0); d1, _ = z_to_date(z1 - 1e-6)
        active = [r for r in rows if r["start"] <= d1 and r["end"] >= d0]
        by_period = {}
        for r in active:
            by_period.setdefault(r["period"], []).append(r)
        taken, pieces = None, []
        for pn in sorted(by_period, key=lambda k: (periods[k]["start"], k), reverse=True):  # o mais novo por cima
            terr = unary_union([geoms[(r["place"], r["kind"])] for r in by_period[pn]])
            own = terr if taken is None else terr.difference(taken)
            taken = terr if taken is None else taken.union(terr)
            for p in polys(own.simplify(SIMPLIFY)):
                key = (pn, hashlib.md5(p.wkb).hexdigest())
                if key not in shape_ids:
                    shape_ids[key] = len(shapes)
                    shapes.append({"period": pn, "rings": rings(p), "area": round(p.area, 1)})
                pieces.append(shape_ids[key])
        union = taken if taken is not None else Polygon()
        bridges = []
        if prev_union is not None:
            for comp in polys(union):
                sup = comp.intersection(prev_union).area
                if sup < 1.0:
                    c = comp.representative_point()
                    bridges.append({"x": round(c.x, 1), "y": round(c.y, 1), "area": round(comp.area, 1)})
        area = union.area
        perim = sum(p.length for p in polys(union))
        layers.append({"i": i, "z0": round(z0, 2), "d0": round(d0, 1), "d1": round(d1, 1), "disc": disc,
                       "periods": sorted(by_period), "places": sorted({r["place"] for r in active}),
                       "pieces": pieces, "bridges": bridges, "area": round(area, 1), "cut": round(perim, 1)})
        csv_rows.append([i + 1, round(z0, 1), round(d0), round(d1), DISCS[disc][2], len(polys(union)),
                         len(bridges), round(area / 100, 1), round(perim / 10, 1),
                         " · ".join(str(p) for p in sorted(by_period))])
        prev_union = union
    stats = {"layers": n, "bridges": sum(len(l["bridges"]) for l in layers),
             "cardboard_m2": round(sum(l["area"] for l in layers) / 1e6, 2),
             "cut_m": round(sum(l["cut"] for l in layers) / 1000, 1),
             "empty_layers": [l["i"] + 1 for l in layers if not l["pieces"]]}
    return {"thickness": t, "shapes": shapes, "layers": layers, "stats": stats}, csv_rows


# --- Pranchas -------------------------------------------------------------
def svg_doc(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}" '
            f'font-family="Helvetica, Arial, sans-serif"><title>{title}</title><rect width="{w}" height="{h}" fill="#fff"/>{body}</svg>')

def path_d(rs, ox=0, oy=0):
    return "".join("M" + " L".join(f"{x+ox:.1f},{y+oy:.1f}" for x, y in r) + "Z" for r in rs)

def plates(model, periods, land, colors):
    out = ROOT / "out" / "plates"; out.mkdir(parents=True, exist_ok=True)
    t = model["thickness"]; S = model["shapes"]; L = model["layers"]
    land_d = "".join(path_d(rings(p)) for p in polys(land))
    tag = f"{t:g}mm"
    # Planta por disco
    for di, (a, b, name) in enumerate(DISCS):
        body = [f'<g transform="translate(20,30)"><path d="{land_d}" fill="#f1eee8" stroke="#cfc8bb" stroke-width="0.2"/>',
                f'<rect width="{W}" height="{D}" fill="none" stroke="#000" stroke-width="0.5"/>']
        ls = [l for l in L if l["disc"] == di]
        for k, l in enumerate(ls):
            for sid in l["pieces"]:
                s = S[sid]
                body.append(f'<path d="{path_d(s["rings"])}" fill="none" stroke="{colors[s["period"]]}" '
                            f'stroke-width="0.25" stroke-opacity="{0.35 + 0.65 * k / max(1, len(ls) - 1):.2f}"/>')
            for br in l["bridges"]:
                body.append(f'<circle cx="{br["x"]}" cy="{br["y"]}" r="2.5" fill="none" stroke="#d00" stroke-width="0.6"/>')
        body.append('</g>')
        leg = sorted({S[s]["period"] for l in ls for s in l["pieces"]})
        body.append(f'<text x="20" y="14" font-size="7" font-weight="bold">Disque {di+1} — {name} ({a} → {b}) · planta 1:1 · papelão {tag}</text>')
        body.append(f'<text x="20" y="23" font-size="4.5">{len(ls)} camadas · contornos mais escuros = mais altos · círculo vermelho = ponte (arame) · {sum(len(l["bridges"]) for l in ls)} pontes</text>')
        for j, pn in enumerate(leg):
            y = 345 + 7 * j
            body.append(f'<rect x="20" y="{y-4}" width="5" height="5" fill="{colors[pn]}"/><text x="28" y="{y}" font-size="4.5">{pn}. {periods[pn]["name"]} ({periods[pn]["start"]} → {periods[pn]["end"]})</text>')
        (out / f"plan-disque-{di+1}-{tag}.svg").write_text(svg_doc(540, 350 + 7 * len(leg), "".join(body), f"Disque {di+1}"))
    # Elevações
    for view in ("face", "droite"):
        ext = W if view == "face" else D
        body = [f'<g transform="translate(60,{H+20}) scale(1,-1)">']
        for l in L:
            for sid in l["pieces"]:
                s = S[sid]
                xs = [x for x, y in s["rings"][0]] if view == "face" else [D - y for x, y in s["rings"][0]]
                body.append(f'<rect x="{min(xs):.1f}" y="{l["z0"]:.2f}" width="{max(xs)-min(xs):.1f}" height="{t}" '
                            f'fill="{colors[s["period"]]}" fill-opacity="0.55"/>')
        body.append(f'<rect width="{ext}" height="{H}" fill="none" stroke="#000" stroke-width="0.5"/>')
        for di in range(1, len(DISCS)):
            body.append(f'<line x1="0" y1="{di*DISC_H}" x2="{ext}" y2="{di*DISC_H}" stroke="#000" stroke-width="0.3" stroke-dasharray="3,2"/>')
        body.append('</g>')
        for di, (a, b, name) in enumerate(DISCS):
            yb = H + 20 - di * DISC_H
            body.append(f'<text x="56" y="{yb-1}" font-size="5" text-anchor="end">{a}</text>')
            body.append(f'<text x="4" y="{yb - DISC_H/2}" font-size="5">{name}</text>')
        body.append(f'<text x="56" y="23" font-size="5" text-anchor="end">{DISCS[-1][1]}</text>')
        sub = "oeste ← → leste (vista de frente)" if view == "face" else "sul (frente) ← → norte (parede do fundo) — vista da direita"
        body.append(f'<text x="60" y="12" font-size="7" font-weight="bold">Elevação {view} 1:1 · papelão {tag} · {sub}</text>')
        body.append(f'<text x="60" y="{H+30}" font-size="4.5">Cada faixa = extensão de um pedaço numa camada. Linhas tracejadas = limites dos discos (19 cm).</text>')
        (out / f"elevation-{view}-{tag}.svg").write_text(svg_doc(int(ext) + 80, int(H) + 40, "".join(body), f"Elevação {view}"))


def palette(periods):
    cols = {}
    for n in periods:
        hue = (n - 1) * 360 / len(periods) * 0.83
        cols[n] = f"hsl({hue:.0f},55%,{48 if n % 2 else 38}%)"
    return cols


def main():
    periods, rows = read_note()
    (ROOT / "data").mkdir(exist_ok=True)
    with open(ROOT / "data" / "territoires.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["period", "place", "kind", "start", "end", "in_notes", "source"])
        for r in rows: w.writerow([r[k] for k in ("period", "place", "kind", "start", "end", "in_notes", "source")])
    countries, land = load_world()
    geoms = {(r["place"], r["kind"]): place_geom(r["place"], r["kind"], countries, land) for r in rows}
    colors = palette(periods)
    docs = ROOT / "docs"; docs.mkdir(exist_ok=True)
    meta = {"volume": {"W": W, "D": D, "H": H, "disc_h": DISC_H},
            "discs": [{"start": a, "end": b, "name": n} for a, b, n in DISCS],
            "periods": [dict(periods[n], color=colors[n], z_start=round(date_to_z(max(periods[n]["start"], DISCS[0][0])), 1),
                             z_end=round(date_to_z(min(periods[n]["end"], DISCS[-1][1])), 1)) for n in sorted(periods)],
            "rows": rows, "land": [rings(p) for p in polys(land.simplify(0.4))],
            "cities": {k: [round(c, 1) for c in proj(*v)] for k, v in VILLES.items()}}
    (docs / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    for t in THICKNESSES:
        model, csv_rows = build(t, periods, rows, geoms)
        (docs / f"layers-{t:g}.json").write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")))
        out = ROOT / "out" / "plates"; out.mkdir(parents=True, exist_ok=True)
        with open(out / f"layers-{t:g}mm.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["camada", "z_mm", "data_ini", "data_fim", "disco", "pedacos", "pontes", "area_cm2", "corte_cm", "periodos"])
            w.writerows(csv_rows)
        plates(model, periods, land, colors)
        print(f"{t:g} mm:", json.dumps(model["stats"], ensure_ascii=False), f"shapes={len(model['shapes'])}")


if __name__ == "__main__":
    main()
