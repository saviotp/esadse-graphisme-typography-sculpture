"""Arquivos de corte a laser: encaixa as peças de cada camada nas chapas de papelão.

Uso:  .venv/bin/python generator/cut.py [generator/cut_config.json]

Lê docs/layers-<espessura>.json (gerado por build.py) e escreve em out/cut/<espessura>mm/:
  sheet-NN.svg   uma chapa por arquivo, em mm reais: vermelho = corte, azul = gravação,
                 verde = contorno da chapa (referência, NÃO cortar)
  montage.csv    peça → chapa, camada, disco, furos
  summary.json   totais

Cada peça leva gravado o número da camada (e uma letra quando a camada tem mais de um pedaço)
e uma seta que aponta o norte (a parede do fundo). Os furos de alinhamento caem numa grade
global: duas camadas vizinhas que contêm o mesmo ponto da grade têm o furo no mesmo lugar,
e o arame ou palito atravessa a pilha.
"""
import csv, json, math, sys
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve
from shapely import affinity
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union
from skimage.draw import polygon as raster_polygon

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "generator" / "cut_config.json").read_text())
T = CFG["thickness_mm"]; GAP = CFG["gap_mm"]; MARGIN = CFG["margin_mm"]; RES = CFG["grid_mm"]
HOLE_R = CFG["hole_diameter_mm"] / 2; HGRID = CFG["hole_grid_mm"]; HEDGE = CFG["hole_edge_mm"]
COL = CFG["colors"]; ENG_W = CFG.get("engrave_width_mm", 0.4)

model = json.loads((ROOT / "docs" / f"layers-{T:g}.json").read_text())
meta = json.loads((ROOT / "docs" / "meta.json").read_text())
S = model["shapes"]

# Maquete em escala reduzida: 2 = 1:2, uma camada em duas, reduzida à metade (mesma espessura de papelão).
SCALE_N = int(CFG.get("scale_divisor", 1))
ONLY = CFG.get("only_layers")          # [primeira, última], na numeração já reduzida
COUPON = CFG.get("coupon_holes_mm")    # diâmetros a testar com o palito, numa plaquinha à parte
model["layers"] = model["layers"][::SCALE_N]
for new_i, L in enumerate(model["layers"]): L["i"] = new_i

def poly(r): return affinity.scale(Polygon(r[0], r[1:]).buffer(0), 1 / SCALE_N, 1 / SCALE_N, origin=(0, 0))
def comps(g):
    if g.is_empty: return []
    return [c for c in (g.geoms if hasattr(g, "geoms") else [g]) if c.area >= 4]


# --- Peças e furos ---------------------------------------------------------
def grid_points(p):
    inner = p.buffer(-(HEDGE + HOLE_R))
    if inner.is_empty: return []
    x0, y0, x1, y1 = inner.bounds
    pts = []
    for gx in np.arange(math.ceil(x0 / HGRID) * HGRID, x1 + 1e-6, HGRID):
        for gy in np.arange(math.ceil(y0 / HGRID) * HGRID, y1 + 1e-6, HGRID):
            if inner.contains(Point(gx, gy)): pts.append((round(gx, 1), round(gy, 1)))
    return pts

def pick_holes(p, prev):
    cand = grid_points(p)
    if not cand:   # peça pequena: um furo no centro, se couber
        c = p.representative_point()
        return [(round(c.x, 1), round(c.y, 1))] if p.buffer(-(HOLE_R + 2)).contains(c) else []
    keep = [q for q in cand if q in prev]
    chosen = []
    pool = keep if keep else cand
    a = max(pool, key=lambda q: Point(q).distance(p.exterior))       # o mais central primeiro
    chosen.append(a)
    rest = [q for q in (keep + cand) if q != a]
    if rest:
        b = max(rest, key=lambda q: (q in prev, math.dist(q, a)))   # continuidade, depois distância
        if math.dist(a, b) >= HGRID: chosen.append(b)
    return chosen

parts = []
prev = set()
for L in model["layers"]:
    u = unary_union([poly(r) for r in L["outline"]])        # contorno real da camada, não a soma das cores
    cs = sorted(comps(u), key=lambda c: c.centroid.x)
    now = set()
    for j, c in enumerate(cs):
        holes = pick_holes(c, prev)
        now.update(holes)
        lab = f"{L['i'] + 1:03d}" + (chr(ord("a") + j) if len(cs) > 1 else "")
        bridge = any(c.distance(Point(b["x"] / SCALE_N, b["y"] / SCALE_N)) < 1 for b in L["bridges"])
        parts.append({"id": lab, "layer": L["i"] + 1, "disc": L["disc"] + 1, "geom": c, "holes": holes, "bridge": bridge})
    prev = now

# O filtro vem depois do laço: os furos continuam alinhados entre os lotes cortados em dias diferentes.
if ONLY: parts = [p for p in parts if ONLY[0] <= p["layer"] <= ONLY[1]]
if COUPON:
    n_c = len(COUPON)
    box = Polygon([(0, 0), (20 * (n_c + 1), 0), (20 * (n_c + 1), 30), (0, 30)])
    parts.append({"id": "e", "layer": 0, "disc": 0, "geom": box, "holes": [(20.0 * (k + 1), 10.0) for k in range(n_c)],
                  "hole_d": COUPON, "bridge": False})


# --- Gravação: algarismos de 7 segmentos (traço simples) e seta do norte ----
SEG = {"a": ((0, 0), (1, 0)), "b": ((1, 0), (1, 1)), "c": ((1, 1), (1, 2)), "d": ((0, 2), (1, 2)),
       "e": ((0, 1), (0, 2)), "f": ((0, 0), (0, 1)), "g": ((0, 1), (1, 1))}
DIG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
       "7": "abc", "8": "abcdefg", "9": "abcdfg"}
LET = {"a": "abcefg", "b": "fedcg", "c": "gde", "d": "bcdeg", "e": "afged", "f": "afge"}

def label_lines(text, h):
    w = h / 2; lines = []; x = 0
    for ch in text:
        for s in (DIG.get(ch) or LET.get(ch, "")):
            (x0, y0), (x1, y1) = SEG[s]
            lines.append(LineString([(x + x0 * w, y0 * h / 2), (x + x1 * w, y1 * h / 2)]))
        x += w * 1.6
    # seta do norte (para cima = -y no mapa)
    ax = x + w * 0.4
    lines += [LineString([(ax, h), (ax, 0)]), LineString([(ax - w * 0.45, h * 0.35), (ax, 0), (ax + w * 0.45, h * 0.35)])]
    return lines, ax + w * 0.5

def engraving(p, holes, text):
    for h in (6.0, 4.5, 3.2):
        lines, width = label_lines(text, h)
        box_w, box_h = width, h
        safe = p.buffer(-1.5)
        for hx, hy in holes: safe = safe.difference(Point(hx, hy).buffer(HOLE_R + 1.5))
        c = p.representative_point()
        for dx, dy in [(0, 0), (-box_w, 0), (0, -box_h), (-box_w, -box_h), (-box_w / 2, -box_h / 2), (-box_w / 2, 4), (-box_w / 2, -box_h - 4)]:
            ox, oy = c.x + dx, c.y + dy
            b = Polygon([(ox, oy), (ox + box_w, oy), (ox + box_w, oy + box_h), (ox, oy + box_h)])
            if safe.contains(b):
                return [affinity.translate(l, ox, oy) for l in lines]
    return []   # peça pequena demais: sem gravação (aparece no montage.csv)


# --- Encaixe (nesting) por raster ---------------------------------------------
def raster(g, ox, oy, shape):
    m = np.zeros(shape, dtype=np.float32)
    for c in comps(g):
        xs, ys = c.exterior.coords.xy
        rr, cc = raster_polygon((np.array(ys) - oy) / RES, (np.array(xs) - ox) / RES, shape)
        m[rr, cc] = 1
    return m

def oriented(p, deg):
    q = affinity.rotate(p, deg, origin=(0, 0))
    x0, y0, _, _ = q.bounds
    return q, (x0, y0)

panels = []
for spec in CFG["panels"]:
    for k in range(spec["count"]):
        panels.append({"id": f"{spec['id']}-{k + 1}", "w": spec["w"], "h": spec["h"],
                       "occ": np.zeros((int(spec["h"] / RES), int(spec["w"] / RES)), dtype=np.float32), "items": []})

# Faixa já cortada no ensaio, na primeira chapa: (x0, y0, x1, y1) em mm, nada é encaixado ali.
RES_RECT = CFG.get("reserved_first_panel")
if RES_RECT and panels:
    x0, y0, x1, y1 = RES_RECT
    panels[0]["occ"][int(y0 / RES):int(math.ceil(y1 / RES)), int(x0 / RES):int(math.ceil(x1 / RES))] = 1

order = sorted(parts, key=lambda p: (p["disc"], -p["geom"].area))
unplaced = []
for pt in order:
    done = False
    for sh in panels:
        if done: break
        best = None
        for deg in CFG["rotations_deg"]:
            q, (qx, qy) = oriented(pt["geom"], deg)
            pad = q.buffer(GAP / 2 + RES)
            px0, py0, px1, py1 = pad.bounds
            mh, mw = int(math.ceil((py1 - py0) / RES)) + 1, int(math.ceil((px1 - px0) / RES)) + 1
            m_marg = int(math.ceil(MARGIN / RES))
            if mh > sh["occ"].shape[0] - 2 * m_marg or mw > sh["occ"].shape[1] - 2 * m_marg: continue
            mask = raster(pad, px0, py0, (mh, mw))
            area = sh["occ"][m_marg:sh["occ"].shape[0] - m_marg, m_marg:sh["occ"].shape[1] - m_marg]
            ov = fftconvolve(area, mask[::-1, ::-1], mode="valid")
            free = np.argwhere(ov < 0.5)
            if not len(free): continue
            r, c = free[np.lexsort((free[:, 1], free[:, 0]))][0]   # mais acima, depois mais à esquerda
            score = (r + mh, c)
            if best is None or score < best[0]:
                best = (score, deg, r + m_marg, c + m_marg, mask, px0, py0)
        if best:
            _, deg, r, c, mask, px0, py0 = best
            sh["occ"][r:r + mask.shape[0], c:c + mask.shape[1]] += mask
            sh["items"].append({"part": pt, "deg": deg, "dx": c * RES - px0, "dy": r * RES - py0})
            done = True
    if not done: unplaced.append(pt["id"])


# --- SVG por chapa -----------------------------------------------------------
out = ROOT / "out" / "cut" / CFG.get("output", f"{T:g}mm"); out.mkdir(parents=True, exist_ok=True)
for f in out.glob("sheet-*.svg"): f.unlink()
def d_of(g):
    ds = []
    for c in comps(g):
        for ring in [c.exterior, *c.interiors]:
            ds.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in list(ring.coords)[:-1]) + "Z")
    return "".join(ds)

rows = []; used = [s for s in panels if s["items"]]
for n, sh in enumerate(used, 1):
    cut, eng = [], []
    for it in sh["items"]:
        pt = it["part"]
        place = lambda g: affinity.translate(affinity.rotate(g, it["deg"], origin=(0, 0)), it["dx"], it["dy"])
        cut.append(d_of(place(pt["geom"])))
        for k, (hx, hy) in enumerate(pt["holes"]):
            r = pt["hole_d"][k] / 2 if "hole_d" in pt else HOLE_R
            cut.append(d_of(place(Point(hx, hy).buffer(r, 16))))
        for l in engraving(pt["geom"], pt["holes"], pt["id"]):
            eng.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in place(l).coords))
        rows.append([pt["id"], pt["layer"], pt["disc"], f"{n:02d}", sh["id"], it["deg"], len(pt["holes"]),
                     "oui" if pt["bridge"] else "", round(pt["geom"].area / 100, 1)])
    w, h = sh["w"], sh["h"]
    if CFG.get("guide_laser"):
        # Guia da découpe laser 2026 (p. 11): corte = contorno de 0,001 pt; gravação = forma PREENCHIDA de preto;
        # nada de contorno de referência no arquivo (a máquina o leria como traço) nem de sobreposição.
        eng_polys = []
        for it in sh["items"]:
            pt = it["part"]
            place = lambda g: affinity.translate(affinity.rotate(g, it["deg"], origin=(0, 0)), it["dx"], it["dy"])
            for l in engraving(pt["geom"], pt["holes"], pt["id"]):
                eng_polys.append(place(l).buffer(ENG_W / 2, 4))
        eng_d = d_of(unary_union(eng_polys)) if eng_polys else ""
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">\n'
               f'<g id="decoupe" fill="none" stroke="#000000" stroke-width="0.00035"><path d="{"".join(cut)}"/></g>\n'
               f'<g id="gravure" fill="#000000" fill-rule="evenodd" stroke="none"><path d="{eng_d}"/></g>\n'
               f'</svg>\n')
    else:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">\n'
               f'<g id="reference-ne-pas-decouper" fill="none" stroke="{COL["reference"]}" stroke-width="0.3" stroke-dasharray="4,3">'
               f'<rect x="0" y="0" width="{w}" height="{h}"/></g>\n'
               f'<g id="decoupe" fill="none" stroke="{COL["cut"]}" stroke-width="0.01"><path d="{"".join(cut)}"/></g>\n'
               f'<g id="gravure" fill="none" stroke="{COL["engrave"]}" stroke-width="0.01"><path d="{" ".join(eng)}"/></g>\n'
               f'</svg>\n')
    (out / f"sheet-{n:02d}.svg").write_text(svg)

with open(out / "montage.csv", "w", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["piece", "couche", "disque", "planche", "carton", "rotation", "trous", "sans_appui", "aire_cm2"])
    wr.writerows(sorted(rows, key=lambda r: r[0]))
summary = {"provisoire": CFG.get("_comment", ""), "thickness_mm": T, "parts": len(parts), "sheets": len(used),
           "unplaced": unplaced, "holes": sum(len(p["holes"]) for p in parts),
           "cut_m": round(sum(p["geom"].length + len(p["holes"]) * 2 * math.pi * HOLE_R for p in parts) / 1000, 1),
           "fragile_necks_lt_4mm": [p["id"] for p in parts if len(comps(p["geom"].buffer(-2).buffer(2))) > 1],
           "parts_without_label": [p["id"] for p in parts if not engraving(p["geom"], p["holes"], p["id"])],
           "fill_ratio": [round(sum(it["part"]["geom"].area for it in s["items"]) / (s["w"] * s["h"]), 2) for s in used]}
(out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
print(json.dumps({k: v if not isinstance(v, list) or len(v) < 12 else f"{len(v)} itens" for k, v in summary.items()}, ensure_ascii=False))
