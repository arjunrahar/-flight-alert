"""
Flight price alert: scans every departure date in a window, finds the cheapest
one-way (or round-trip) fare per date on Google Flights, and sends a push
notification (ntfy.sh) and/or email when any fare is below your threshold.

Everything is configured with environment variables (see README.md); the
defaults below match ATL -> DEL, 2026-11-20 .. 2026-12-30, under $550.
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
import time
import urllib.request
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_query, get_flights

# ----------------------------------------------------------------- config ---
ORIGIN = os.getenv("ORIGIN", "ATL")
DEST = os.getenv("DEST", "DEL")
START = date.fromisoformat(os.getenv("START_DATE", "2026-11-20"))
END = date.fromisoformat(os.getenv("END_DATE", "2026-12-30"))
THRESHOLD = float(os.getenv("THRESHOLD_USD", "550"))
TRIP = os.getenv("TRIP", "one-way")            # "one-way" or "round-trip"
RETURN_DAYS = int(os.getenv("RETURN_DAYS", "21"))  # only used for round-trip
MAX_STOPS = os.getenv("MAX_STOPS")               # e.g. "1"; empty = any
DELAY_SEC = float(os.getenv("DELAY_SEC", "1.5"))  # pause between Google requests
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")        # ntfy.sh topic name
EMAIL_TO = os.getenv("EMAIL_TO", "")
SMTP_USER = os.getenv("SMTP_USER", "")          # e.g. your Gmail address
SMTP_PASS = os.getenv("SMTP_PASS", "")          # Gmail "app password"
ALWAYS_NOTIFY = os.getenv("ALWAYS_NOTIFY", "0") == "1"  # send summary every run
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
HISTORY_FILE = Path(os.getenv("HISTORY_FILE", "history.csv"))


def date_range(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def cheapest_for(dep: date, retries: int = 2):
    """Return (price, airlines, route) for the cheapest itinerary on `dep`, or None."""
    flights = [FlightQuery(date=dep.isoformat(), from_airport=ORIGIN, to_airport=DEST)]
    if TRIP == "round-trip":
        ret = dep + timedelta(days=RETURN_DAYS)
        flights.append(FlightQuery(date=ret.isoformat(), from_airport=DEST, to_airport=ORIGIN))
    q = create_query(
        flights=flights,
        trip=TRIP,
        seat="economy",
        passengers=Passengers(adults=1),
        currency="USD",
        language="en",
        max_stops=int(MAX_STOPS) if MAX_STOPS else None,
    )
    for attempt in range(retries + 1):
        try:
            results = get_flights(q)
            priced = [f for f in results if f.price and f.price > 0]
            if not priced:
                raise RuntimeError("no priced results")
            best = min(priced, key=lambda f: f.price)
            route = " > ".join(s.from_airport.code for s in best.flights) + " > " + best.flights[-1].to_airport.code
            return best.price, "/".join(best.airlines), route, q.url()
        except Exception as e:  # network hiccup, Google layout change, captcha...
            if attempt == retries:
                print(f"  {dep}: FAILED ({e})", file=sys.stderr)
                return None
            time.sleep(3 * (attempt + 1))


def notify(title: str, body: str, url: str | None = None):
    sent = []
    if NTFY_TOPIC:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode(),
            headers={"Title": title, "Priority": "high", "Tags": "airplane",
                     **({"Click": url} if url else {})},
        )
        urllib.request.urlopen(req, timeout=20).read()
        sent.append("ntfy")
    if EMAIL_TO and SMTP_USER and SMTP_PASS:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = title, SMTP_USER, EMAIL_TO
        msg.set_content(body + (f"\n\n{url}" if url else ""))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        sent.append("email")
    if not sent:
        print("  (no notification channel configured; printing only)")
    return sent


def main():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    alerted = state.setdefault("alerted", {})   # date -> last price we alerted at
    today = date.today()
    dates = [d for d in date_range(START, END) if d >= today]
    print(f"{ORIGIN}->{DEST} {TRIP}, {len(dates)} dates, threshold ${THRESHOLD:.0f}")

    rows, hits = [], []
    for d in dates:
        r = cheapest_for(d)
        time.sleep(DELAY_SEC)
        if r is None:
            continue
        price, airline, route, url = r
        rows.append((d, price, airline, route, url))
        flag = " <-- BELOW THRESHOLD" if price < THRESHOLD else ""
        print(f"  {d}  ${price:>5}  {airline:<28} {route}{flag}")
        if price < THRESHOLD:
            prev = alerted.get(d.isoformat())
            # alert if never alerted for this date, or it dropped another $10+
            if prev is None or price <= prev - 10:
                hits.append((d, price, airline, route, url))

    if not rows:
        print("Every request failed; nothing to report.", file=sys.stderr)
        sys.exit(1)

    # append to history for later plotting / sanity checks
    new = not HISTORY_FILE.exists()
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        if new:
            f.write("checked_at,depart,price_usd,airlines,route\n")
        for d, price, airline, route, _ in rows:
            f.write(f"{today},{d},{price},{airline},{route}\n")

    overall = min(rows, key=lambda r: r[1])
    summary = f"Cheapest: ${overall[1]} on {overall[0]} ({overall[2]}, {overall[3]})"
    print(summary)

    if hits:
        hits.sort(key=lambda h: h[1])
        lines = [f"{d:%a %b %d}: ${p} {a} ({rt})" for d, p, a, rt, _ in hits]
        title = f"{ORIGIN}->{DEST} fare under ${THRESHOLD:.0f}: ${hits[0][1]}"
        notify(title, "\n".join(lines), hits[0][4])
        for d, p, *_ in hits:
            alerted[d.isoformat()] = p
        print(f"ALERT sent for {len(hits)} date(s)")
    elif ALWAYS_NOTIFY:
        notify(f"{ORIGIN}->{DEST} check: nothing under ${THRESHOLD:.0f}", summary, overall[4])

    state["last_run"] = today.isoformat()
    state["last_cheapest"] = {"date": overall[0].isoformat(), "price": overall[1]}
    STATE_FILE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
