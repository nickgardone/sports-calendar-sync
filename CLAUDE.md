# Sports Team Schedule Importer — Project Briefing

## What This Is
A web app that lets users connect their Google Calendar and sync a full sports team schedule to it in one click. Supports NFL, NBA, MLB, NHL, MLS, WNBA, PGA Tour, NASCAR, and UFC. Built originally as a Python CLI, then wrapped in a Flask web UI and deployed to Render.com.

---

## Deployment
- **Live URL:** https://sports-team-schedule-importer.onrender.com
- **GitHub:** https://github.com/nickgardone/Sports-Team-Schedule-Importer
- **Hosting:** Render.com free tier (spins down after inactivity, ~50s cold start)
- **Auto-deploy:** NOT enabled — user must click Manual Deploy in Render after each push
- **Branch:** main

---

## File Structure
```
Sports Calendar/
├── app.py                  # Flask web server — all routes
├── espn_client.py          # ESPN unofficial API wrapper (schedule fetching)
├── google_calendar.py      # Google Calendar API client (desktop + web OAuth)
├── leagues.py              # League config dict + aliases
├── main.py                 # Original CLI entry point (still works)
├── requirements.txt        # flask, gunicorn, google-api-python-client, requests
├── render.yaml             # Render.com deploy config
├── SETUP.md                # CLI setup instructions
├── .gitignore              # Excludes credentials.json, token.json, *credentials*.json
├── templates/
│   ├── index.html          # Main UI (landing + authenticated app, privacy modal)
│   ├── error.html          # Error display page
│   └── privacy.html        # Privacy policy (hosted at /privacy for Google review)
└── static/
    └── style.css           # All styles — mobile responsive
```

---

## Architecture

### Backend (app.py)
Flask server. Routes:
- `GET /` — landing page (unauthenticated) or main app UI (authenticated)
- `GET /oauth/start` — builds Google OAuth URL manually (no PKCE), redirects to Google
- `GET /oauth/callback` — exchanges auth code for token via direct HTTP POST to Google
- `GET /logout` — clears session
- `GET /privacy` — privacy policy page (for Google verification URL submission)
- `GET /error` — error display page
- `POST /api/search` — ESPN team search, returns JSON list of matching teams
- `GET /api/calendars` — returns user's Google Calendar list
- `POST /api/sync` — fetches schedule + creates calendar events, returns JSON summary

### OAuth Implementation (IMPORTANT)
Uses **plain authorization-code flow with direct HTTP calls** — NOT google-auth-oauthlib Flow.
Reason: Flow object was causing PKCE code_verifier errors on Render's stateless server.
The manual approach (`requests.post` to `https://oauth2.googleapis.com/token`) works reliably.
Credentials stored in Flask session cookie (encrypted). No server-side database.

### ESPN Data (espn_client.py)
Unofficial ESPN API — no key required.
- Team sports: `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/schedule`
- PGA/NASCAR: weekly sweep of scoreboard endpoint (PGA returns 48 events/year)
- NASCAR slug: `nascar-premier` (NOT `nascar-premier-series`)
- Returns game dicts: `{title, start_utc, duration_hours, location, league, is_home, status, description}`

### Google Calendar (google_calendar.py)
Two classes:
- `GoogleCalendarClient` — desktop OAuth (used by CLI/main.py)
- `GoogleCalendarWebClient` — accepts credentials dict from Flask session
Both support `color_id` parameter (Google Calendar colorId 1–11).
`CALENDAR_COLORS` list defines all 11 colors with hex values for the UI color picker.

---

## Google Cloud Setup
- **Project:** Sports Calendar (ID: 642711868528)
- **OAuth credentials:** Two credentials exist:
  1. Desktop app — for CLI use (`credentials.json`, gitignored)
  2. Web application — for the hosted app (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` env vars)
- **Authorized redirect URIs on web credential:**
  - `http://localhost:5000/oauth/callback`
  - `https://sports-team-schedule-importer.onrender.com/oauth/callback`
- **App status:** External, testing mode. Only approved test users can sign in currently.
- **Google verification:** In progress — submitting for full verification to allow any user.
  Privacy policy URL: `https://sports-team-schedule-importer.onrender.com/privacy`

---

## Render.com Environment Variables
Set in Render dashboard → Environment:
- `GOOGLE_CLIENT_ID` — from Web Application OAuth credential
- `GOOGLE_CLIENT_SECRET` — from Web Application OAuth credential
- `SECRET_KEY` — Flask session encryption key (user-defined string)

---

## Key UI Details (index.html + style.css)
- **Unauthenticated:** Hero landing page with "Connect Google Calendar" button + feature list + Privacy Policy footer
- **Authenticated:** Two-step flow:
  1. League dropdown (with chevron arrow) + team search → results as clickable cards
  2. Calendar selector + color picker (11 Google Calendar color swatches) + sync button
- **Non-team sports** (PGA/NASCAR/UFC): team search hidden, "Load Full Schedule" button shown
- **Privacy Policy:** Opens as scrollable modal overlay (✕ to close, click backdrop, or Escape). Also accessible at `/privacy` for Google's review.
- **Error states:** Inline alert if schedule not available yet; error page for auth failures
- **Color picker:** 11 swatches + "Calendar default" option. Selected colorId sent to `/api/sync`

---

## CLI Usage (still works)
```bash
cd ~/Documents/Business/AI\ Projects/Sports\ Calendar
python3 main.py "Buffalo Bills"
python3 main.py "Lakers" --league NBA
python3 main.py --league PGA
```
Requires `credentials.json` (Desktop app type) in the project folder.

---

## What's Been Tested / Working
- ✅ CLI tool: Buffalo Bills 17-game schedule synced successfully
- ✅ Events colored tomato red via direct API patch
- ✅ Web app deployed and live on Render.com
- ✅ Google OAuth sign-in working (after fixing PKCE issue)
- ✅ Privacy policy modal on landing page
- ✅ League dropdown with chevron arrow
- ✅ GitHub repo: all code committed, credentials excluded

## What's Pending / In Progress
- 🔲 Google app verification (allows any user, not just test users)
- 🔲 Polish updates to the UI (user had more changes in mind — ask them)
- 🔲 Render auto-deploy not configured (must manually deploy after each push)

---

## Owner
Nick Gardone — ngardone@gmail.com
