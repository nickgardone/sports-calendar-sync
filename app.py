import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests as http_requests
from flask import (
    Flask, session, redirect, url_for, request,
    jsonify, render_template, Response
)

from espn_client import ESPNClient
from google_calendar import (
    CALENDAR_COLORS,
    GoogleCalendarWebClient,
)
from leagues import LEAGUE_CONFIG

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')


# ---------------------------------------------------------------------------
# Upstash Redis — sync counter (social proof)
# Graceful degradation: if env vars are absent the counter is simply hidden.
# ---------------------------------------------------------------------------

_UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
_UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
_COUNTER_KEY   = 'total_syncs'


def _redis_headers():
    return {'Authorization': f'Bearer {_UPSTASH_TOKEN}'}


def _get_sync_count():
    """Return the current sync count (int) or None if Redis is unavailable."""
    if not _UPSTASH_URL or not _UPSTASH_TOKEN:
        return None
    try:
        resp = http_requests.get(
            f'{_UPSTASH_URL}/get/{_COUNTER_KEY}',
            headers=_redis_headers(),
            timeout=2,
        )
        result = resp.json().get('result')
        return int(result) if result is not None else 0
    except Exception:
        return None


def _increment_sync_count():
    """Increment the sync counter. Fire-and-forget — never raises."""
    if not _UPSTASH_URL or not _UPSTASH_TOKEN:
        return
    try:
        http_requests.post(
            f'{_UPSTASH_URL}/incr/{_COUNTER_KEY}',
            headers=_redis_headers(),
            timeout=2,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Airtable — anonymous sync event log (team, calendar, timestamp)
# Graceful degradation: no-op if env vars are absent.
# ---------------------------------------------------------------------------

_AIRTABLE_PAT   = os.environ.get('AIRTABLE_PAT', '')
_AIRTABLE_BASE  = os.environ.get('AIRTABLE_BASE_ID', '')
_AIRTABLE_TABLE = os.environ.get('AIRTABLE_TABLE_NAME', 'Sync Events')


def _log_sync_event(team_name: str, calendar_type: str):
    if not _AIRTABLE_PAT or not _AIRTABLE_BASE:
        return
    try:
        http_requests.post(
            f'https://api.airtable.com/v0/{_AIRTABLE_BASE}/{_AIRTABLE_TABLE}',
            headers={
                'Authorization': f'Bearer {_AIRTABLE_PAT}',
                'Content-Type': 'application/json',
            },
            json={'fields': {
                'Team':      team_name,
                'Calendar':  calendar_type,
                'Timestamp': datetime.now(timezone.utc).isoformat(),
            }},
            timeout=3,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ICS (iCalendar) helpers for Apple Calendar / .ics download
# ---------------------------------------------------------------------------

def _ics_escape(s):
    """Escape special characters for iCalendar property values (RFC 5545)."""
    if not s:
        return ''
    return str(s).replace('\\', '\\\\').replace('\n', '\\n').replace(',', '\\,').replace(';', '\\;')


def _ics_fold(line):
    """Fold lines longer than 75 octets per RFC 5545 §3.1."""
    if len(line.encode('utf-8')) <= 75:
        return line
    result = []
    while len(line.encode('utf-8')) > 75:
        cut = 75
        # Walk back from 75 to avoid splitting a multibyte character
        while cut > 0:
            try:
                line[:cut].encode('utf-8')
                break
            except UnicodeDecodeError:
                cut -= 1
        result.append(line[:cut])
        line = ' ' + line[cut:]
    result.append(line)
    return '\r\n'.join(result)


def generate_ics(games, calendar_name):
    """Return an iCalendar string (.ics) for a list of game dicts."""
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Sports Schedule Importer//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        _ics_fold(f'X-WR-CALNAME:{_ics_escape(calendar_name)}'),
    ]

    for i, game in enumerate(games):
        try:
            start_dt = game.get('start_utc')
            if start_dt is None:
                continue
            # Accepts both datetime objects and ISO strings
            if isinstance(start_dt, str):
                start_dt = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            end_dt = start_dt + timedelta(hours=game.get('duration_hours', 3))
            dtstart = start_dt.strftime('%Y%m%dT%H%M%SZ')
            dtend   = end_dt.strftime('%Y%m%dT%H%M%SZ')
            uid     = game.get('uid') or f'sports-{i}-{dtstart}@sports-schedule-importer'

            lines.append('BEGIN:VEVENT')
            lines.append(f'UID:{uid}')
            lines.append(f'DTSTART:{dtstart}')
            lines.append(f'DTEND:{dtend}')
            lines.append(_ics_fold(f'SUMMARY:{_ics_escape(game.get("title", "Game"))}'))
            if game.get('location'):
                lines.append(_ics_fold(f'LOCATION:{_ics_escape(game["location"])}'))
            if game.get('description'):
                lines.append(_ics_fold(f'DESCRIPTION:{_ics_escape(game["description"])}'))
            lines.append('END:VEVENT')
        except Exception:
            continue

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    authed = 'credentials' in session
    user_email = session.get('user_email')
    leagues = list(LEAGUE_CONFIG.keys())
    team_based = {k: v['team_based'] for k, v in LEAGUE_CONFIG.items()}
    sync_count = _get_sync_count()
    return render_template(
        'index.html',
        authed=authed,
        user_email=user_email,
        leagues=leagues,
        team_based=team_based,
        colors=CALENDAR_COLORS,
        sync_count=sync_count,
    )


@app.route('/error')
def error_page():
    msg = request.args.get('msg', 'Something went wrong.')
    return render_template('error.html', message=msg)


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


# ---------------------------------------------------------------------------
# OAuth  (plain authorization-code flow, no PKCE — correct for server-side apps)
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL  = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_SCOPES    = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]

def _callback_uri():
    return url_for('oauth_callback', _external=True)


@app.route('/oauth/start')
def oauth_start():
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    if not client_id:
        return redirect(url_for('error_page', msg=(
            'Google OAuth credentials are not configured. '
            'Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.'
        )))

    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    params = {
        'client_id':     client_id,
        'redirect_uri':  _callback_uri(),
        'response_type': 'code',
        'scope':         ' '.join(GOOGLE_SCOPES),
        'access_type':   'offline',
        'prompt':        'consent',
        'state':         state,
    }
    return redirect(GOOGLE_AUTH_URL + '?' + urlencode(params))


@app.route('/oauth/callback')
def oauth_callback():
    if 'error' in request.args:
        return redirect(url_for('error_page', msg=f"Google OAuth error: {request.args['error']}"))

    code = request.args.get('code')
    if not code:
        return redirect(url_for('error_page', msg='No authorization code received from Google.'))

    try:
        # Exchange the authorization code for tokens — no PKCE needed
        token_resp = http_requests.post(GOOGLE_TOKEN_URL, data={
            'code':          code,
            'client_id':     os.environ.get('GOOGLE_CLIENT_ID'),
            'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET'),
            'redirect_uri':  _callback_uri(),
            'grant_type':    'authorization_code',
        })
        token_json = token_resp.json()

        if 'error' in token_json:
            raise ValueError(token_json.get('error_description', token_json['error']))

        session['credentials'] = {
            'token':         token_json['access_token'],
            'refresh_token': token_json.get('refresh_token'),
            'token_uri':     GOOGLE_TOKEN_URL,
            'client_id':     os.environ.get('GOOGLE_CLIENT_ID'),
            'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET'),
            'scopes':        GOOGLE_SCOPES,
        }

        # Fetch the user's email for display
        user_resp = http_requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f"Bearer {token_json['access_token']}"},
        )
        session['user_email'] = user_resp.json().get('email', '')

    except Exception as e:
        return redirect(url_for('error_page', msg=f"Failed to complete sign-in: {e}"))

    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route('/api/teams')
def api_teams():
    """Return all teams for a league, sorted alphabetically."""
    league_key = request.args.get('league', '').upper()
    if league_key not in LEAGUE_CONFIG:
        return jsonify({'error': 'Unknown league'}), 400
    if not LEAGUE_CONFIG[league_key].get('team_based'):
        return jsonify([])
    espn = ESPNClient()
    teams = espn.list_teams(league_key)
    return jsonify(teams)


@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.get_json() or {}
    team = data.get('team', '').strip()
    league = data.get('league') or None

    if not team:
        return jsonify([])

    espn = ESPNClient()
    results = espn.search_teams(team, league)
    return jsonify(results)


@app.route('/api/calendars')
def api_calendars():
    if 'credentials' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    try:
        gcal = GoogleCalendarWebClient(session['credentials'])
        cals = gcal.list_calendars()
        return jsonify([
            {'id': c['id'], 'name': c.get('summary', c['id'])}
            for c in cals
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/season')
def api_season():
    """
    Return the active season year for a team/league, but only if the schedule
    contains at least one future game. A season that exists but is fully in the
    past (e.g. NHL 2025-26 in June 2026) is treated as unavailable so users
    aren't offered a calendar full of already-played games.

    Used by the Apple Calendar flow to lock the season into the webcal:// URL
    and by the Google Calendar pre-flight check.
    Returns: { "season": 2026 } or { "season": null } if unavailable.
    """
    team_id    = request.args.get('team_id') or None
    league_key = request.args.get('league', '').upper()

    if league_key not in LEAGUE_CONFIG:
        return jsonify({'error': 'Unknown league'}), 400

    cfg  = LEAGUE_CONFIG[league_key]
    espn = ESPNClient()
    now  = datetime.now(timezone.utc)

    if cfg['team_based']:
        events, season_year = espn.get_team_schedule(team_id, league_key)
        if events and season_year:
            # Confirm at least one game is in the future.
            # If the whole season is in the past, treat as unavailable.
            has_future = False
            for ev in events:
                date_str = ev.get('date', '')
                if not date_str:
                    comps = ev.get('competitions', [{}])
                    date_str = comps[0].get('date', '') if comps else ''
                if date_str:
                    try:
                        ev_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        if ev_dt > now:
                            has_future = True
                            break
                    except Exception:
                        pass
            if not has_future:
                season_year = None
    else:
        events      = espn.get_event_schedule(league_key)
        season_year = datetime.now().year if events else None

    return jsonify({'season': season_year})


@app.route('/api/track-apple', methods=['POST'])
def api_track_apple():
    data = request.get_json(silent=True) or {}
    team_name = data.get('team_name', 'Unknown')
    _increment_sync_count()
    _log_sync_event(team_name, 'Apple')
    return jsonify({'ok': True})


@app.route('/api/sync', methods=['POST'])
def api_sync():
    if 'credentials' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json() or {}
    team_id   = data.get('team_id')
    team_name = data.get('team_name', '')
    league_key = data.get('league', '').upper()
    calendar_id = data.get('calendar_id', 'primary')
    user_tz   = data.get('timezone', 'America/New_York')
    color_id  = data.get('color_id') or None   # '' → None

    if league_key not in LEAGUE_CONFIG:
        return jsonify({'error': f'Unknown league: {league_key}'}), 400

    cfg = LEAGUE_CONFIG[league_key]
    espn = ESPNClient()

    if cfg['team_based']:
        events, season_year = espn.get_team_schedule(team_id, league_key)
        if not events:
            return jsonify({
                'status': 'no_schedule',
                'message': (
                    f"The {team_name} schedule for {datetime.now().year} "
                    f"hasn't been released yet. Check back closer to the season start."
                ),
            })
        games = [espn.parse_team_game(e, team_id, team_name, league_key) for e in events]
    else:
        events = espn.get_event_schedule(league_key)
        if not events:
            return jsonify({
                'status': 'no_schedule',
                'message': (
                    f"The {league_key} schedule hasn't been released yet. Check back later."
                ),
            })
        games = [espn.parse_event_game(e, league_key) for e in events]

    games = [g for g in games if g]

    try:
        gcal = GoogleCalendarWebClient(session['credentials'], calendar_id)
        created, skipped, errors = gcal.add_schedule(games, user_tz, color_id=color_id)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    _increment_sync_count()
    _log_sync_event(team_name, 'Google')
    return jsonify({
        'status': 'success',
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'total': len(games),
    })


@app.route('/ics')
def serve_ics():
    """
    Live .ics feed for Apple Calendar subscriptions (webcal:// protocol).

    The `season` query param locks this feed to a specific season year so Apple
    Calendar's periodic refreshes never automatically pull in the following year's
    schedule. When the season ends, a single reminder event is injected at
    approximately the start of next season — it appears in the user's Apple Calendar
    as a prompt to come back to the app (and eventually pay, per Option A).

    GET /ics?team_id=<id>&league=NFL&team_name=Buffalo+Bills&season=2026
    """
    team_id    = request.args.get('team_id') or None
    team_name  = request.args.get('team_name', '')
    league_key = request.args.get('league', '').upper()
    season     = request.args.get('season') or None   # locked season year

    if league_key not in LEAGUE_CONFIG:
        return Response('', status=400)

    cal_name = team_name or league_key
    cfg      = LEAGUE_CONFIG[league_key]
    espn     = ESPNClient()

    if cfg['team_based']:
        events, _ = espn.get_team_schedule(team_id, league_key, season=season)
        games = [espn.parse_team_game(e, team_id, team_name, league_key) for e in events] if events else []
    else:
        events = espn.get_event_schedule(league_key)
        games  = [espn.parse_event_game(e, league_key) for e in events] if events else []

    games = [g for g in games if g]

    # ── Tollgate: end-of-season reminder ────────────────────────────────────
    # Once all games are in the past, check whether the NEXT season's schedule
    # is already live on ESPN. If it is, inject a reminder event dated TODAY so
    # it appears in Apple Calendar immediately — no waiting until next fall.
    # If the new schedule isn't out yet, inject nothing; Apple Calendar will keep
    # refreshing the subscription until it is, then the reminder appears.
    # This is sports-agnostic: NFL (May release), NBA (Aug), MLB (Nov), etc. all
    # handled correctly without hardcoding any dates.
    #
    # The UID is stable (team + season, not current time) so Apple Calendar
    # updates the existing event on each refresh rather than creating duplicates.
    #
    # Future hook (Option A): payment check slots in here — return reminder only
    # after the user has paid for the new season.
    if season and games:
        def _to_aware(dt):
            return dt if getattr(dt, 'tzinfo', None) else dt.replace(tzinfo=timezone.utc)

        now_utc   = datetime.now(timezone.utc)
        last_game = max(_to_aware(g['start_utc']) for g in games)

        if last_game < now_utc:
            # All games are in the past — season is over.
            # Ask ESPN whether next season's data is available yet.
            next_year      = int(season) + 1
            next_available = False

            if cfg['team_based']:
                next_events, _ = espn.get_team_schedule(team_id, league_key, season=str(next_year))
                next_available  = bool(next_events)
            else:
                # Non-team sports: check if any event from the live feed is in next_year
                raw = espn.get_event_schedule(league_key)
                for ev in (raw or []):
                    d = ev.get('date', '')
                    if d:
                        try:
                            if datetime.fromisoformat(d.replace('Z', '+00:00')).year >= next_year:
                                next_available = True
                                break
                        except Exception:
                            pass

            if next_available:
                # New schedule is live — remind the user today.
                # DTSTART floats to today so it always appears as current/upcoming
                # until the user acts on it.
                app_url     = request.host_url.rstrip('/')
                today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                games.append({
                    'title':          f'Sync {cal_name} {next_year} schedule',
                    'start_utc':      today_start,
                    'duration_hours': 24,
                    'uid':            f'tollgate-{league_key}-{team_id or "noteam"}-{season}@sports-schedule-importer',
                    'location':       '',
                    'description': (
                        f'The {cal_name} {next_year} schedule is now available!\n\n'
                        f'Visit {app_url} to sync the {next_year} season to your calendar.'
                    ),
                })
            # Next season not out yet — no reminder injected.
            # Apple Calendar keeps refreshing; reminder appears once ESPN has the data.
    # ── End tollgate ─────────────────────────────────────────────────────────

    ics_content = generate_ics(games, cal_name)
    safe        = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '' for c in cal_name)
    filename    = safe.replace(' ', '_') + '_Schedule.ics'

    return Response(
        ics_content,
        mimetype='text/calendar; charset=utf-8',
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )


if __name__ == '__main__':
    app.run(debug=True)
