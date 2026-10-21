"""Envía por correo (Gmail) el parte diario del radar y, los lunes, el resumen semanal.

Secretos necesarios en GitHub (Settings > Secrets and variables > Actions):
  GMAIL_USER          tu dirección de Gmail (la que envía)
  GMAIL_APP_PASSWORD  «contraseña de aplicación» de 16 letras (no tu contraseña normal)
  AVISO_EMAIL         opcional: a quién enviarlo; varias direcciones separadas por comas (por defecto, a ti mismo)
Si faltan, el script no envía nada y no da error.
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MADRID = ZoneInfo("Europe/Madrid")


def eur(x: float) -> str:
    return f"{x:+.2f} €".replace(".", ",")


def legs_txt(d: dict) -> str:
    return " + ".join(f"{escape(l['label'])} ({escape(l['home'])} – {escape(l['away'])}, {l['o']:.2f})" for l in d["legs"])


def system_line(name: str, items: list, stake_key: str = "stake") -> str:
    done = [x for x in items if x.get("status") in ("ganada", "perdida")]
    pnl = sum(x.get("pnl", 0) for x in done)
    staked = sum(x.get(stake_key, 0) for x in done)
    won = sum(1 for x in done if x["status"] == "ganada")
    y = f" · yield {pnl / staked:+.1%}" if staked else ""
    return f"<li><b>{name}</b>: {eur(pnl)} ({won}/{len(done)} acertadas{y}, {len(items) - len(done)} pendientes)</li>"


def build(sim: dict, feed: dict, now: datetime) -> tuple[str, str]:
    today = now.strftime("%Y-%m-%d")
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    h = [f"<h2>Radar de cuotas · {now.strftime('%d/%m/%Y')}</h2>",
         "<p style='color:#8f5a0a'>Simulación con dinero ficticio. Ninguna apuesta es segura.</p>"]

    h.append("<h3>Para hoy</h3><ul>")
    picks = 0
    for key, name in (("daily", "Apuesta del día"), ("favs", "Combinada de favoritos")):
        for d in sim.get(key, []):
            if d["day"] == today:
                h.append(f"<li><b>{name}</b> ({d['tipo']}, cuota {d['O']:.2f}, 5 €): {legs_txt(d)}</li>")
                picks += 1
    for b in sim.get("bets", []):
        if b.get("placedAt", "")[:10] == today or (b["status"] == "pendiente" and b["date"] == today):
            h.append(f"<li><b>Con valor</b>: {escape(b['label'])} · {escape(b['home'])} – {escape(b['away'])} "
                     f"({b['date']} {b.get('time', '')}) a {b['o']:.2f}, stake sugerido {b['stake']:.2f} €, EV {b['ev']:+.1%}</li>")
            picks += 1
    if not picks:
        h.append("<li>Nada nuevo hoy: ningún partido supera los filtros. Lo correcto es no apostar.</li>")
    h.append("</ul>")

    res = []
    for key, name in (("daily", "Apuesta del día"), ("favs", "Combinada de favoritos")):
        for d in sim.get(key, []):
            if d["status"] != "pendiente" and d["day"] >= yday:
                res.append(f"<li>{name} del {d['day']}: <b>{d['status']}</b> ({eur(d.get('pnl', 0))}) · {legs_txt(d)}</li>")
    for b in sim.get("bets", []):
        if b["status"] != "pendiente" and b.get("settledAt", "")[:10] >= yday:
            res.append(f"<li>Con valor: {escape(b['label'])} · {escape(b['home'])} – {escape(b['away'])} {b.get('result', '')}: "
                       f"<b>{b['status']}</b> ({eur(b.get('pnl', 0))})</li>")
    if res:
        h.append("<h3>Resultados recientes</h3><ul>" + "".join(res) + "</ul>")

    h.append("<h3>Cómo va cada sistema</h3><ul>")
    h.append(system_line("Apuestas con valor", sim.get("bets", [])))
    h.append(system_line("Apuesta del día", sim.get("daily", [])))
    h.append(system_line("Combinada de favoritos", sim.get("favs", [])))
    h.append(system_line("Laboratorio de favoritos", sim.get("favSingles", [])))
    h.append("</ul>")

    if now.weekday() == 0 or os.environ.get("FORZAR_RESUMEN"):
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        h.append("<h3>Resumen de la semana</h3><ul>")
        for key, name, dk in (("bets", "Apuestas con valor", "date"), ("daily", "Apuesta del día", "day"),
                              ("favs", "Combinada de favoritos", "day"), ("favSingles", "Laboratorio de favoritos", "date")):
            week = [x for x in sim.get(key, []) if start <= x.get(dk, "") < today]
            h.append(system_line(name, week))
        h.append("</ul><p>Con pocas semanas el resultado es sobre todo suerte: fíjate más en si la tendencia se mantiene.</p>")

    if feed.get("avisos"):
        h.append("<p style='color:#b42318'>Avisos de la actualización: " + escape(" · ".join(feed["avisos"][:4])) + "</p>")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        h.append(f"<p><a href='https://{owner}.github.io/{name}/'>Abrir el radar</a></p>")
    subject = f"Radar de cuotas {now.strftime('%d/%m')}: " + (f"{picks} propuesta(s) para hoy" if picks else "hoy no apostar")
    return subject, "\n".join(h)


def main() -> int:
    user, pwd = os.environ.get("GMAIL_USER", "").strip(), os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    to = [x.strip() for x in os.environ.get("AVISO_EMAIL", "").replace(";", ",").split(",") if x.strip()] or [user]
    sim_p, feed_p = ROOT / "datos" / "simulador.json", ROOT / "datos" / "datos.json"
    sim = json.loads(sim_p.read_text(encoding="utf-8")) if sim_p.exists() else {}
    feed = json.loads(feed_p.read_text(encoding="utf-8")) if feed_p.exists() else {}
    subject, html = build(sim, feed, datetime.now(MADRID))
    if not user or not pwd:
        print("Sin GMAIL_USER / GMAIL_APP_PASSWORD: no se envía correo.\n" + subject)
        return 0
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, to, msg.as_string())
    print(f"Correo enviado a {', '.join(to)}: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
