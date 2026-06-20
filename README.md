# Sports Calendar Sync

Add your favorite team's full season schedule to Google Calendar or Apple Calendar in seconds — no manual entry, no CSV files.

**Live app:** [sports-team-schedule-importer.onrender.com](https://sports-team-schedule-importer.onrender.com)

---

## Features

- **9 leagues supported** — NFL, NBA, MLB, NHL, MLS, WNBA, PGA Tour, NASCAR, UFC
- **Google Calendar sync** — OAuth sign-in, direct event creation with custom color support, duplicate detection
- **Apple Calendar subscription** — One-tap webcal:// subscribe, no sign-in required, auto-updates as the schedule changes
- **Home & away labeling** — Events show "Bills vs. Chiefs" (home) or "Bills @ Chiefs" (away)
- **Season availability check** — Warns immediately if a team's schedule hasn't been released yet
- **No data stored** — OAuth tokens live only in an encrypted session cookie; nothing is written to a database

---

## How It Works

1. Visit the app and choose **Google Calendar** or **Apple Calendar**
2. Select your league from the dropdown
3. Select your team
4. For Google Calendar: sign in with Google, pick a calendar and optional event color, click **Add to Calendar**
5. For Apple Calendar: tap **Add to Apple Calendar** and subscribe when prompted

Schedule data is fetched from ESPN's public API at sync time. Apple Calendar subscriptions stay live and update automatically when ESPN updates its data.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · Flask · Gunicorn |
| Schedule data | ESPN public API |
| Google Calendar | Google Calendar API v3 (OAuth 2.0) |
| Apple Calendar | webcal:// / iCalendar (RFC 5545) |
| Sync counter | Upstash Redis (REST API) |
| Sync analytics | Airtable (REST API) |
| Hosting | Render.com |

---

## Local Development

### Prerequisites

- Python 3.11+
- A Google Cloud project with the Calendar API enabled and OAuth credentials

### Setup

```bash
git clone https://github.com/nickgardone/sports-calendar-sync.git
cd sports-calendar-sync
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment variables

Create a `.env` file (never commit this):

```
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
FLASK_SECRET_KEY=any_random_string
UPSTASH_REDIS_REST_URL=your_upstash_url        # optional — sync counter
UPSTASH_REDIS_REST_TOKEN=your_upstash_token    # optional — sync counter
AIRTABLE_PAT=your_personal_access_token        # optional — sync analytics
AIRTABLE_BASE_ID=appXXXXXXXX                   # optional — sync analytics
AIRTABLE_TABLE_NAME=Sync Events                # optional — sync analytics
```

### Run

```bash
flask run
```

Open [http://localhost:5000](http://localhost:5000).

---

## Project Structure

```
app.py               # Flask routes and OAuth flow
espn_client.py       # ESPN API client (team search, schedule fetch, ICS generation)
google_calendar.py   # Google Calendar API client (web OAuth + CLI)
leagues.py           # League configuration (sport, slug, duration, team-based flag)
main.py              # CLI entry point (local testing)
templates/
  index.html         # Main app UI
  privacy.html       # Privacy policy page
static/
  style.css          # All styles
render.yaml          # Render deployment config
```

---

## Privacy

The app does not store any user data. Google OAuth tokens are held only in an encrypted session cookie for the duration of the browser session. No calendar data, email addresses, or personal information is written to any server-side storage. Full details at [/privacy](https://sports-team-schedule-importer.onrender.com/privacy).

---

## License

MIT
