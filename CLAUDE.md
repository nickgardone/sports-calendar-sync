# Sports Calendar Sync — Project Briefing

## What This Is
A web app that lets users connect their Google Calendar or Apple Calendar and sync a full sports team schedule in one click. Supports NFL, NBA, MLB, NHL, MLS, WNBA, PGA Tour, NASCAR, and UFC. Built originally as a Python CLI, then wrapped in a Flask web UI and deployed to Render.com.

---

## Deployment
- **Live URL:** https://sports-team-schedule-importer.onrender.com
- **GitHub:** https://github.com/nickgardone/sports-calendar-sync
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
- `GET /api/season` — returns active season year for a team/league (used by Apple Calendar flow)
- `POST /api/sync` — fetches schedule + creates Google Calendar events, returns JSON summary
- `GET /ics` — serves live iCalendar (.ics) feed for Apple Calendar webcal:// subscriptions

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
- `get_team_schedule()` accepts optional `season` param to lock to a specific year
- Season fallback: tries current year → next year. Never falls back to previous year (prevents stale data in Apple Calendar subscriptions)
- Returns game dicts: `{title, start_utc, duration_hours, location, league, is_home, status, description}`

### Google Calendar (google_calendar.py)
Two classes:
- `GoogleCalendarClient` — desktop OAuth (used by CLI/main.py)
- `GoogleCalendarWebClient` — accepts credentials dict from Flask session
Both support `color_id` parameter (Google Calendar colorId 1–11).
`CALENDAR_COLORS` list defines all 11 colors with hex values for the UI color picker.

### Apple Calendar / ICS (app.py)
- `generate_ics()` — manual RFC 5545 iCalendar generator (no external library)
- `_ics_escape()` / `_ics_fold()` — helpers for proper ICS formatting
- `GET /ics` — serves live .ics feed; accepts `season` param to lock to specific year
- `GET /api/season` — lightweight endpoint to determine active season year for a team

---

## Calendar Type Choice (Landing Page)
The unauthenticated landing page presents two options:
1. **Google Calendar** — OAuth sign-in → direct event sync with color picker
2. **Apple Calendar** — no sign-in required → webcal:// subscription

### Apple Calendar Flow (no auth required)
1. User clicks "Use Apple Calendar" → hero section hides, Apple search section appears
2. Step 1: League dropdown + team search (same ESPN search as Google flow)
3. JS calls `GET /api/season?team_id=X&league=Y` to determine active season year
4. If season found: "Add to Apple Calendar" button appears with locked webcal:// URL
5. If no season: "Schedule not available yet" warning shown
6. User taps button → prompted to subscribe → games appear immediately
7. Confirmation message: "When prompted, tap Subscribe — your [team] schedule will appear in Apple Calendar within seconds."

### webcal:// Subscription Details
- Protocol is intercepted by iOS/macOS and opens Apple Calendar natively
- Season year is locked in URL: `webcal://host/ics?team_id=X&league=NFL&team_name=Bills&season=2026`
- Apple Calendar refreshes the URL periodically (hourly to daily)
- Each refresh returns only the locked season's data — never auto-advances to next year

---

## Season Tollgate (Apple Calendar)
Prevents Apple Calendar from auto-importing the following year's schedule.
Foundation for Option A monetization (Stripe payment gate) to be added later.

### How it works
1. Season year locked in webcal:// URL at subscription time (via `/api/season`)
2. `/ics` endpoint always returns data for the locked year only
3. When all games are in the past (season over):
   - Checks ESPN for next year's schedule availability
   - If **not available**: nothing injected — Apple Calendar keeps refreshing silently
   - If **available**: injects a reminder event dated TODAY: *"🔔 Sync [Team] [Year+1] schedule"* with link back to app
4. Reminder event UID is stable (`tollgate-{league}-{team_id}-{season}@sports-schedule-importer`) so Apple Calendar updates the event rather than creating duplicates
5. Reminder appears the moment ESPN releases the new schedule — sports-agnostic (no hardcoded dates)

### Option A (Future Monetization — NOT YET BUILT)
- Stripe Checkout + signed JWT token approach
- `/api/season` is the payment gate hook: currently returns season year freely; will require payment verification before returning
- Signed token contains: team_id, league, season_year, expiry (1 year)
- Token embedded in webcal:// URL; `/ics` validates token before serving schedule
- No database needed — JWT is self-contained proof of purchase
- Price point TBD (originally discussed at $1-3/team/season; Stripe fees ~$0.30+2.9% per transaction)

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

### Unauthenticated Landing
- Hero card with two calendar options: "Connect Google Calendar" + "Use Apple Calendar"
- Clicking Apple Calendar hides hero, shows Apple search flow (no OAuth needed)
- "← Back" button returns to the calendar choice
- Feature list: 9 leagues, Google Calendar, Apple Calendar, home/away labeling, privacy

### Google Calendar Flow (authenticated)
- Two-step: League dropdown + team search → calendar selector + color picker + sync button
- Non-team sports (PGA/NASCAR/UFC): team search hidden, "Load Full Schedule" button shown
- Success message includes "Open Google Calendar →" link to calendar.google.com
- Color picker: 11 swatches + "Calendar default" option

### Apple Calendar Flow (unauthenticated)
- Step 1: Same league/team search as Google flow
- When team selected: JS calls /api/season (shows loading state on button)
- Step 2: "Add to Apple Calendar" link (webcal:// URL with season locked)
- Confirmation shown immediately on tap: "When prompted, tap Subscribe — your [team] schedule will appear in Apple Calendar within seconds."

### Privacy Policy
- Footer button opens scrollable modal overlay (no navigation away from page)
- Also accessible at `/privacy` for Google's review URL submission

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
- ✅ Apple Calendar flow: webcal:// subscription, season lock, tollgate, reminder event
- ✅ Confirmation messages for both Google and Apple Calendar flows
- ✅ GitHub repo: all code committed, credentials excluded

## What's Pending / In Progress
- 🔲 Google app verification (allows any user, not just test users)
- 🔲 Option A monetization: Stripe Checkout + signed JWT token (foundation built, payment not wired)
- 🔲 Render auto-deploy not configured (must manually deploy after each push)
- 🔲 Additional UI polish (ask user what they have in mind)

---

## Owner
Nick Gardone — ngardone@gmail.com
