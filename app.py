import os
from datetime import datetime

from flask import (
    Flask, session, redirect, url_for, request,
    jsonify, render_template
)

from espn_client import ESPNClient
from google_calendar import (
    CALENDAR_COLORS,
    GoogleCalendarWebClient,
    create_web_flow,
)
from leagues import LEAGUE_CONFIG

# Allow HTTP for local development (Render.com uses HTTPS automatically)
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

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
# OAuth
# ---------------------------------------------------------------------------

def _callback_uri():
    return url_for('oauth_callback', _external=True)


@app.route('/oauth/start')
def oauth_start():
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        return redirect(url_for('error_page', msg=(
            'Google OAuth credentials are not configured. '
            'Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.'
        )))

    flow = create_web_flow(_callback_uri())
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    session['oauth_state'] = state
    # Persist PKCE code verifier across the Google redirect
    try:
        session['code_verifier'] = flow.oauth2session._client.code_verifier
    except AttributeError:
        pass
    return redirect(auth_url)


@app.route('/oauth/callback')
def oauth_callback():
    if 'error' in request.args:
        return redirect(url_for('error_page', msg=f"Google OAuth error: {request.args['error']}"))

    try:
        flow = create_web_flow(_callback_uri())
        # Restore PKCE code verifier if it was saved during oauth_start
        code_verifier = session.pop('code_verifier', None)
        fetch_kwargs = {'authorization_response': request.url}
        if code_verifier:
            fetch_kwargs['code_verifier'] = code_verifier
        flow.fetch_token(**fetch_kwargs)
        creds = flow.credentials
        session['credentials'] = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': list(creds.scopes) if creds.scopes else [],
        }
        # Fetch the user's email for display
        from googleapiclient.discovery import build
        oauth2 = build('oauth2', 'v2', credentials=creds)
        info = oauth2.userinfo().get().execute()
        session['user_email'] = info.get('email', '')
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
