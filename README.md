# Flight price alert (ATL -> DEL under $550)

Scans every departure date from 2026-11-20 to 2026-12-30, pulls the cheapest
one-way fare per date from Google Flights, and pushes a notification to your
phone (and/or email) when any fare is below $550. Nothing to sign up for on the
flight-data side: it reads Google Flights directly via the `fast-flights` library.

## 1. Get notified on your phone (2 minutes)
1. Install the **ntfy** app (iOS / Android) or open https://ntfy.sh in a browser.
2. Subscribe to the topic name in `.env.example` (`NTFY_TOPIC`). Pick your own
   random name if you like; anyone who knows the topic name can see alerts.
3. Optional email: set `EMAIL_TO`, `SMTP_USER` (your Gmail) and `SMTP_PASS`
   (a Gmail *App Password*, not your login password).

## 2. Run it once on this PC
```powershell
cd "$HOME\flight-alert"
pip install -r requirements.txt
copy .env.example .env      # edit if you want to change anything
.\run_local.ps1
```
Set `ALWAYS_NOTIFY=1` in `.env` for one run to confirm the notification arrives.

## 3. Keep it running
Pick one:

**A. GitHub Actions (recommended: free, runs even when your PC is off)**
```powershell
cd "$HOME\flight-alert"
git init -b main
git add .
git commit -m "flight price alert"
# create an empty PRIVATE repo on github.com named flight-alert, then:
git remote add origin https://github.com/<you>/flight-alert.git
git push -u origin main
```
Then in the repo: Settings -> Secrets and variables -> Actions -> **New repository secret**
`NTFY_TOPIC` = your topic (plus the SMTP ones if you want email). The workflow in
`.github/workflows/check.yml` runs every 6 hours and you can trigger it manually
from the Actions tab to test. Delete the repo (or disable the workflow) after you book.

**B. Windows Task Scheduler (only runs while this PC is on and awake)**
```powershell
schtasks /Create /TN "FlightPriceCheck" /SC HOURLY /MO 6 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"$HOME\flight-alert\run_local.ps1\"" /F
```
Remove later with `schtasks /Delete /TN "FlightPriceCheck" /F`.

## How alerts work
- One alert per date the first time it dips under the threshold, and again only
  if it drops another $10+. State lives in `state.json`; every observed price is
  appended to `history.csv`.
- `TRIP=round-trip` checks a return `RETURN_DAYS` later. Note that current
  one-way fares on this route are ~$1000+, so a $550 round trip is unlikely.
- Google occasionally blocks scrapers; failed dates are skipped and retried on
  the next run. If every date fails for a day, the job exits non-zero so you'll
  see a red run in GitHub Actions.
