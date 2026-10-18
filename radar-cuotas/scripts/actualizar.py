"""Actualiza datos/datos.json para el Radar de cuotas.

Se ejecuta cada día en GitHub Actions (también puedes lanzarlo a mano en tu PC):
  1. Descarga de football-data.co.uk los CSV de cada liga (resultados, tiros y cuotas).
     Las temporadas pasadas se descargan una vez; la actual, siempre.
  2. Descarga de The Odds API las cuotas de los próximos partidos (1X2 y más/menos 2,5).
  3. Empareja los nombres de equipos y escribe datos/datos.json, que el radar lee al abrirse.

Si una fuente falla, se conservan los datos anteriores y se anota un aviso: nunca se inventa nada.
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "datos" / "raw"
OUT = ROOT / "datos" / "datos.json"
MADRID = ZoneInfo("Europe/Madrid")

# Todas las ligas principales de football-data (resultados, tiros y cuotas gratis)
LEAGUES = ["E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3", "D1", "D2", "I1", "I2",
           "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
# Ligas que además se consultan en The Odds API (cuotas del día). Cada una gasta 2 créditos por ejecución;
# el resto usa el archivo gratuito de próximos partidos de football-data.
ODDS_API = {
    "E0": "soccer_epl", "E1": "soccer_efl_champ", "SP1": "soccer_spain_la_liga",
    "SP2": "soccer_spain_segunda_division", "D1": "soccer_germany_bundesliga",
    "I1": "soccer_italy_serie_a", "F1": "soccer_france_ligue_one",
}
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
LONDON = ZoneInfo("Europe/London")
SEASONS = ["2425", "2526", "2627"]           # la última es la temporada en curso
FD_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
EXCLUDE_BOOKS = {"pinnacle", "betfair_ex_eu", "betfair_ex_uk", "matchbook", "smarkets"}
UA = {"User-Agent": "Mozilla/5.0 (radar-cuotas; uso personal)"}
ALIASES_FILE = ROOT / "scripts" / "alias.json"


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ football-data
def download_results(avisos: list[str], getter=requests.get) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        for div in LEAGUES:
            path = RAW / f"{div}_{season}.csv"
            if path.exists() and season != SEASONS[-1]:
                continue
            ok = False
            try:
                r = getter(FD_URL.format(season=season, div=div), headers=UA, timeout=30)
                ok = r.status_code == 200 and r.content.lstrip(b"\xef\xbb\xbf").startswith(b"Div")
            except requests.RequestException as exc:
                log(f"  {div} {season}: error de red {exc}")
            if ok:
                path.write_bytes(r.content)
                log(f"  {div} {season}: OK")
            else:
                msg = f"No se pudo descargar {div} {season} de football-data"
                if path.exists():
                    msg += " (se usan los datos anteriores)"
                avisos.append(msg)
                log("  " + msg)
            time.sleep(0.5)


def iso(d: str) -> str | None:
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", (d or "").strip())
    if not m:
        return None
    y = int(m.group(3))
    y = 2000 + y if y < 100 else y
    return f"{y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def read_results() -> dict[str, list]:
    hist: dict[str, list] = {}
    for div in LEAGUES:
        rows = []
        for season in SEASONS:
            path = RAW / f"{div}_{season}.csv"
            if not path.exists():
                continue
            text = path.read_bytes().decode("latin-1").lstrip("\ufeff").lstrip("ï»¿")
            for r in csv.DictReader(io.StringIO(text)):
                d, h, a = iso(r.get("Date", "")), (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
                hg, ag = num(r.get("FTHG")), num(r.get("FTAG"))
                if d and h and a and hg is not None and ag is not None:
                    rows.append([d, h, a, hg, ag, num(r.get("HS")), num(r.get("AS")), num(r.get("HST")), num(r.get("AST"))])
        if rows:
            hist[div] = sorted(rows)
    return hist


# ------------------------------------------------------------------ nombres de equipos
STOP = {"fc", "cf", "afc", "sc", "ac", "cd", "ud", "sd", "rcd", "club", "de", "the", "calcio", "cp", "sad", "sv", "vfb",
        "vfl", "tsg", "ssc", "acf", "as", "us", "ss", "ogc", "rc", "aj", "bc", "1"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


def match_team(name: str, known: list[str], aliases: dict) -> str | None:
    """Emparejamiento prudente: alias, nombre exacto o parecido claro y sin ambigüedad.
    Ante la duda devuelve None (el partido se descarta y se avisa), nunca un equipo equivocado."""
    if name in aliases and aliases[name] in known:
        return aliases[name]
    if name in known:
        return name
    n = norm(name)
    table = {norm(k): k for k in known}
    if n in table:
        return table[n]
    toks = set(n.split())
    generic = {"city", "town", "united", "fc", "club", "hotspur", "albion", "wanderers", "rovers", "county",
               "athletic", "05", "04", "07", "1846", "1899", "1909", "1913", "calcio", "sv", "sc", "cf"}
    subset = [k for kn, k in table.items() if kn and set(kn.split()) <= toks and (toks - set(kn.split())) <= generic]
    if len(subset) == 1:          # «hull» dentro de «hull city», «mainz» dentro de «fsv mainz 05»
        return subset[0]
    scored = sorted(((difflib.SequenceMatcher(None, n, kn).ratio(), k) for kn, k in table.items()), reverse=True)
    if scored and scored[0][0] >= 0.8 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1):
        return scored[0][1]
    return None


# ------------------------------------------------------------------ cuotas
def parse_event(ev: dict, div: str, known: list[str], aliases: dict, now: datetime):
    start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
    if not (now < start < now + timedelta(days=10)):
        return None, None
    h = match_team(ev["home_team"], known, aliases)
    a = match_team(ev["away_team"], known, aliases)
    if not h or not a:
        return None, f"{div}: {ev['home_team']} – {ev['away_team']}"
    prices: dict[str, list] = {}
    pin: dict[str, float] = {}
    books = set()
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            for oc in mk.get("outcomes", []):
                k = None
                if mk["key"] == "h2h":
                    k = ("H" if oc["name"] == ev["home_team"] else "A" if oc["name"] == ev["away_team"]
                         else "D" if oc["name"] == "Draw" else None)
                elif mk["key"] == "totals" and float(oc.get("point", 0)) == 2.5:
                    k = {"Over": "O25", "Under": "U25"}.get(oc["name"])
                if not k:
                    continue
                if bk["key"] == "pinnacle":
                    pin[k] = oc["price"]
                elif bk["key"] not in EXCLUDE_BOOKS:
                    prices.setdefault(k, []).append(oc["price"])
                    books.add(bk["key"])
    if not prices:
        return None, None
    local = start.astimezone(MADRID)
    odds = {"Avg": {k: round(sum(v) / len(v), 3) for k, v in prices.items()},
            "Max": {k: max(v) for k, v in prices.items()}}
    if pin:
        odds["PS"] = pin
    date = local.strftime("%Y-%m-%d")
    return {"id": f"{div}|{date}|{h}|{a}", "div": div, "date": date, "time": local.strftime("%H:%M"),
            "home": h, "away": a, "odds": odds, "src": "the-odds-api", "n_casas": len(books)}, None


def builtin_teams() -> dict[str, set]:
    """Nombres de equipos de los datos integrados en index.html (por si football-data falla)."""
    try:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        i = html.index("const BUILTIN = ") + len("const BUILTIN = ")
        data, _ = json.JSONDecoder().raw_decode(html[i:])
        return {d: {t for r in rows if r[0] >= "2025-07-01" for t in r[1:3]} for d, rows in data["hist"].items()}
    except Exception:
        return {}


def download_odds(hist: dict, avisos: list[str], getter=requests.get) -> tuple[list, list, str | None]:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        avisos.append("Falta ODDS_API_KEY: no se han descargado cuotas.")
        return [], [], None
    aliases = json.loads(ALIASES_FILE.read_text(encoding="utf-8")) if ALIASES_FILE.exists() else {}
    now = datetime.now(timezone.utc)
    fixtures, unmatched, remaining = [], [], None
    fallback = builtin_teams()
    for div, sport in ODDS_API.items():
        params = {"apiKey": key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal", "dateFormat": "iso"}
        try:
            r = getter(ODDS_URL.format(sport=sport), params=params, timeout=30)
        except requests.RequestException as exc:
            avisos.append(f"The Odds API no respondió para {div}: {exc}")
            continue
        remaining = r.headers.get("x-requests-remaining", remaining)
        if r.status_code != 200:
            avisos.append(f"The Odds API devolvió {r.status_code} para {div}: {r.text[:120]}")
            continue
        known = sorted({t for row in hist.get(div, []) if row[0] >= "2025-07-01" for t in row[1:3]} | fallback.get(div, set()))
        for ev in r.json():
            fx, miss = parse_event(ev, div, known, aliases, now)
            if fx:
                fixtures.append(fx)
            if miss:
                unmatched.append(miss)
        time.sleep(0.5)
    return fixtures, unmatched, remaining


def fd_fixtures(avisos: list[str], getter=requests.get) -> list[dict]:
    """Próximos partidos con cuotas de football-data (Bet365, Pinnacle, media y máxima). Horas en hora británica."""
    try:
        r = getter(FIXTURES_URL, headers=UA, timeout=30)
        ok = r.status_code == 200 and b"HomeTeam" in r.content[:400]
    except requests.RequestException:
        ok = False
    if not ok:
        avisos.append("No se pudo descargar el archivo de próximos partidos de football-data.")
        return []
    today = datetime.now(MADRID).strftime("%Y-%m-%d")
    out = []
    text = r.content.decode("latin-1").lstrip("\ufeff").lstrip("ï»¿")  # quita la marca BOM que rompe la columna Div
    for row in csv.DictReader(io.StringIO(text)):
        div = (row.get("Div") or "").strip()
        d = iso(row.get("Date", ""))
        h, a = (row.get("HomeTeam") or "").strip(), (row.get("AwayTeam") or "").strip()
        if div not in LEAGUES or not d or not h or not a:
            continue
        hhmm = (row.get("Time") or "12:00").strip()
        try:
            uk = datetime.strptime(f"{d} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=LONDON)
        except ValueError:
            uk = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=LONDON)
        local = uk.astimezone(MADRID)
        date = local.strftime("%Y-%m-%d")
        if date < today:
            continue
        def g(k):
            try:
                v = float(row.get(k) or "")
                return v if v > 1 else None
            except ValueError:
                return None
        odds = {}
        for name, p1, pt in (("B365", "B365", "B365"), ("PS", "PS", "P"), ("Avg", "Avg", "Avg"), ("Max", "Max", "Max")):
            e = {k: v for k, v in (("H", g(p1 + "H")), ("D", g(p1 + "D")), ("A", g(p1 + "A")),
                                   ("O25", g(pt + ">2.5")), ("U25", g(pt + "<2.5"))) if v}
            if e:
                odds[name] = e
        if odds:
            out.append({"id": f"{div}|{date}|{h}|{a}", "div": div, "date": date, "time": local.strftime("%H:%M"),
                        "home": h, "away": a, "odds": odds, "src": "football-data"})
    return out


def main() -> int:
    avisos: list[str] = []
    log("1/3 Resultados de football-data")
    download_results(avisos)
    hist = read_results()
    log("2/3 Próximos partidos y cuotas")
    base = fd_fixtures(avisos)
    api, unmatched, remaining = download_odds(hist, avisos)
    # las cuotas de la API son del momento; las de football-data se publican antes de cada jornada
    seen = {(f["div"], f["home"], f["away"]) for f in api}
    fixtures = api + [f for f in base if (f["div"], f["home"], f["away"]) not in seen]
    log(f"  football-data: {len(base)} partidos · The Odds API: {len(api)} partidos")
    log("3/3 Escribiendo datos/datos.json")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {"generado": datetime.now(timezone.utc).isoformat(), "hist": hist, "fixtures": fixtures,
            "sin_emparejar": unmatched, "avisos": avisos, "creditos_restantes": remaining}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"Listo: {sum(len(v) for v in hist.values())} resultados, {len(fixtures)} próximos partidos con cuotas, "
        f"{len(unmatched)} sin emparejar, créditos restantes {remaining}.")
    for a in avisos:
        log("AVISO: " + a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
