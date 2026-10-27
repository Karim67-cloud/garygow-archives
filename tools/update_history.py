#!/usr/bin/env python3
"""Met à jour les archives de GARYGOW à partir des fichiers de résultats officiels.

Sorties : history/history-50-2.json (50 numéros + 2 étoiles) et history/history-49-1.json (49 numéros + 1 étoile),
du tirage le plus récent au plus ancien :  {"game":..., "updated":"AAAA-MM-JJ", "draws":[{"d":"AAAA-MM-JJ","n":[...],"s":[...]}]}

Sources (tools/sources.json) : pour chaque jeu, une liste d'adresses (CSV ou ZIP de CSV) ou de fichiers locaux.
Le programme lit les CSV FDJ et les CSV « une ligne par tirage » : il reconnaît les colonnes de date, de boules,
d'étoiles et de numéro chance par leur nom (boule_1..boule_5, etoile_1, etoile_2, numero_chance, star_1…).
Chaque tirage est contrôlé (5 numéros distincts, étoiles dans les bornes) ; les lignes invalides sont comptées et
signalées, jamais écrites. Si le résultat est vide ou plus petit que l'archive déjà publiée, l'ancienne est conservée.

Usage : python3 tools/update_history.py [--sources tools/sources.json] [--out history] [--check]
"""
import argparse, csv, io, json, os, re, sys, unicodedata, urllib.request, zipfile, datetime

GAMES = {
    "50-2": {"name": "50 numéros + 2 étoiles", "N": 50, "ns": 2, "sm": 12},
    "49-1": {"name": "49 numéros + 1 étoile", "N": 49, "ns": 1, "sm": 10},
}

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")

def parse_date(v):
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    return None

def to_int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return None

def rows_from_text(text):
    text = text.lstrip("﻿")
    sample = text[:4000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))

def draws_from_rows(rows, key, stats):
    """Retourne les tirages valides d'un tableau (première ligne = en-têtes)."""
    g = GAMES[key]
    if not rows:
        return []
    head = [norm(h) for h in rows[0]]
    def cols(pats):
        return [i for i, h in enumerate(head) if any(re.fullmatch(p, h) for p in pats)]
    dcol = cols([r"date_de_tirage", r"date", r"draw_date", r"date_tirage", r"drawdate"])
    if not dcol:
        stats["unrecognised"] += 1
        return []
    # Un tableau peut contenir un 2e tirage par ligne (Loto depuis 2019 : colonnes « …_second_tirage »).
    def is2(h):
        return "second" in h or "2eme" in h or "2e_tirage" in h
    out, found = [], False
    for second in (False, True):
        def pick(pats):
            ix = [i for i, h in enumerate(head) if is2(h) == second and any(re.fullmatch(p, re.sub(r"_?(second|2eme|2e)_?tirage", "", h)) for p in pats)]
            return sorted(ix, key=lambda i: head[i])
        ball = pick([r"boule_?[1-5]", r"n_?[1-5]", r"ball_?[1-5]", r"number_?[1-5]", r"num_?[1-5]", r"numero_?[1-5]"])
        if g["ns"] == 2:
            star = pick([r"etoile_?[12]", r"star_?[12]", r"s_?[12]", r"lucky_?star_?[12]"])
        else:
            star = pick([r"numero_chance", r"chance", r"lucky_?number", r"n_chance"])
        if len(ball) != 5 or len(star) != g["ns"]:
            continue
        found = True
        for r in rows[1:]:
            if len(r) <= max(dcol + ball + star):
                stats["skipped"] += 1
                continue
            d = parse_date(r[dcol[0]])
            n = [to_int(r[i]) for i in ball]
            s = [to_int(r[i]) for i in star]
            if second and all(v is None for v in n + s):
                continue   # pas de 2e tirage ce jour-là
            ok = (d and None not in n and None not in s and len(set(n)) == 5 and len(set(s)) == g["ns"]
                  and all(1 <= x <= g["N"] for x in n) and all(1 <= x <= g["sm"] for x in s))
            if not ok:
                stats["skipped"] += 1
                continue
            out.append({"d": d, "n": sorted(n), "s": sorted(s)})
    if not found:
        stats["unrecognised"] += 1
    return out

def read_source(src):
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "GARYGOW-history-updater"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    with open(src, "rb") as f:
        return f.read()

def texts_from_blob(blob):
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                if name.lower().endswith((".csv", ".txt")):
                    yield z.read(name)
    else:
        yield blob

def decode(b):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "ignore")

def build(key, sources, since):
    stats = {"skipped": 0, "unrecognised": 0, "sources": 0}
    seen, draws = set(), []
    for src in sources:
        try:
            blob = read_source(src)
        except Exception as e:
            print(f"  ! source illisible {src} : {e}", file=sys.stderr)
            continue
        stats["sources"] += 1
        for t in texts_from_blob(blob):
            for d in draws_from_rows(rows_from_text(decode(t)), key, stats):
                if since and d["d"] < since:
                    continue
                ident = (d["d"], tuple(d["n"]), tuple(d["s"]))
                if ident in seen:
                    continue
                seen.add(ident)
                draws.append(d)
    draws.sort(key=lambda x: (x["d"], x["n"]), reverse=True)
    return draws, stats

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=os.path.join(os.path.dirname(__file__), "sources.json"))
    ap.add_argument("--out", default="history")
    ap.add_argument("--check", action="store_true", help="contrôle seulement, n'écrit rien")
    a = ap.parse_args()
    cfg = json.load(open(a.sources, encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    code = 0
    for key, g in GAMES.items():
        c = cfg.get(key, {})
        draws, st = build(key, c.get("sources", []), c.get("since"))
        path = os.path.join(a.out, f"history-{key}.json")
        old = 0
        if os.path.exists(path):
            try:
                old = len(json.load(open(path, encoding="utf-8"))["draws"])
            except Exception:
                pass
        print(f"{key}: {len(draws)} tirages valides, {st['skipped']} lignes écartées, "
              f"{st['unrecognised']} tableaux non reconnus, {st['sources']} source(s) lue(s)"
              + (f" ; plus récent : {draws[0]['d']}" if draws else ""))
        if not draws or len(draws) < old * 0.9:
            print(f"  -> archive existante conservée ({old} tirages)", file=sys.stderr)
            code = 1
            continue
        if not a.check:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"game": g["name"], "updated": datetime.date.today().isoformat(), "draws": draws},
                          f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
    sys.exit(code)

if __name__ == "__main__":
    main()
