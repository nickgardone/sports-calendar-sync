import os
import secrets
from datetime import datetime
from urllib.parse import urlencode

import requests as http_requests
from flask import (
    Flask, session, redirect, url_for, request,
    jsonify, render_template
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
# Pages
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    authed = 'credentials' in session
    user_email = session.get('user_email')
    leagues = list(LEAGUE_CONFIG.keys())
    team_based = {k: v['team_based'] for k, v in LEAGUE_CONFIG.items()}
    return render_template(
        'index.html',
        authed=authed,
        user_email=user_email,
        leagues=leagues,
        team_based=team_based,
        colors=CALENDAR_COLORS,
    )


@app.route('/error')
def error_page():
    msg = request.args.get('msg', 'Something went wrong.')
    return render_template('error.html', message=msg)


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

    return jsonify({
        'status': 'success',
        'created': created,
        'skipped': skipped,
        'errors': errors,
        'total': len(games),
    })


if __name__ == '__main__':
    app.run(debug=True)
