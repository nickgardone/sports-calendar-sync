import os
from datetime import timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_FILE = Path(__file__).parent / 'token.json'
CREDENTIALS_FILE = Path(__file__).parent / 'credentials.json'

# Google Calendar event colorId → display name + hex
CALENDAR_COLORS = [
    {'id': '',   'name': 'Calendar default', 'hex': None},
    {'id': '11', 'name': 'Tomato',           'hex': '#D50000'},
    {'id': '4',  'name': 'Flamingo',         'hex': '#E67C73'},
    {'id': '6',  'name': 'Tangerine',        'hex': '#F4511E'},
    {'id': '5',  'name': 'Banana',           'hex': '#F6BF26'},
    {'id': '2',  'name': 'Sage',             'hex': '#33B679'},
    {'id': '10', 'name': 'Basil',            'hex': '#0B8043'},
    {'id': '7',  'name': 'Peacock',          'hex': '#039BE5'},
    {'id': '9',  'name': 'Blueberry',        'hex': '#3F51B5'},
    {'id': '1',  'name': 'Lavender',         'hex': '#7986CB'},
    {'id': '3',  'name': 'Grape',            'hex': '#8E24AA'},
    {'id': '8',  'name': 'Graphite',         'hex': '#616161'},
]


# ---------------------------------------------------------------------------
# Desktop OAuth (used by the CLI / main.py)
# ---------------------------------------------------------------------------

class GoogleCalendarClient:
    def __init__(self, calendar_id='primary'):
        self.calendar_id = calendar_id
        self.service = self._authenticate()

    def _authenticate(self):
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                "Missing credentials.json — see SETUP.md for instructions to create one."
            )

        creds = None
        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
            TOKEN_FILE.write_text(creds.to_json())

        return build('calendar', 'v3', credentials=creds)

    def list_calendars(self):
        result = self.service.calendarList().list().execute()
        return result.get('items', [])

    def _event_exists(self, title, start_dt):
        window_start = (start_dt - timedelta(hours=1)).isoformat()
        window_end = (start_dt + timedelta(hours=1)).isoformat()
        try:
            events = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=window_start,
                timeMax=window_end,
                q=title,
                singleEvents=True,
            ).execute()
            for e in events.get('items', []):
                if e.get('summary', '').strip() == title.strip():
                    return True
        except HttpError:
            pass
        return False

    def create_event(self, game, user_tz='America/New_York', color_id=None):
        start_utc = game['start_utc']
        end_utc = start_utc + timedelta(hours=game['duration_hours'])

        start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ') if start_utc.tzinfo else start_utc.isoformat() + 'Z'
        end_str = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ') if end_utc.tzinfo else end_utc.isoformat() + 'Z'

        title = game['title']
        if self._event_exists(title, start_utc):
            return 'exists', None

        body = {
            'summary': title,
            'description': game.get('description', ''),
            'start': {'dateTime': start_str, 'timeZone': 'UTC'},
            'end':   {'dateTime': end_str,   'timeZone': 'UTC'},
        }
        if game.get('location'):
            body['location'] = game['location']
        if color_id:
            body['colorId'] = str(color_id)

        try:
            created = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
            return 'created', created.get('htmlLink')
        except HttpError as e:
            return 'error', str(e)

    def add_schedule(self, games, user_tz='America/New_York', color_id=None):
        created = skipped = errors = 0
        total = len(games)
        for i, game in enumerate(games, 1):
            status, detail = self.create_event(game, user_tz, color_id=color_id)
            if status == 'created':
                created += 1
                print(f"  [{i}/{total}] Added: {game['title']} ({game['start_utc'].strftime('%b %-d')})")
            elif status == 'exists':
                skipped += 1
            else:
                errors += 1
                print(f"  [{i}/{total}] Error adding {game['title']}: {detail}")
        return created, skipped, errors


# ---------------------------------------------------------------------------
# Web OAuth helpers (used by app.py / Flask)
# ---------------------------------------------------------------------------

def create_web_flow(redirect_uri):
    """Create a Google OAuth Flow for the web app using env var credentials."""
    client_config = {
        "web": {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


class GoogleCalendarWebClient:
    """
    Google Calendar client for web app usage.
    Accepts a credentials dict stored in the Flask session rather than token.json.
    """
    def __init__(self, credentials_dict, calendar_id='primary'):
        self.calendar_id = calendar_id
        creds = Credentials(
            token=credentials_dict['token'],
            refresh_token=credentials_dict.get('refresh_token'),
            token_uri=credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=credentials_dict.get('client_id'),
            client_secret=credentials_dict.get('client_secret'),
            scopes=credentials_dict.get('scopes'),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        self.service = build('calendar', 'v3', credentials=creds)

    def list_calendars(self):
        result = self.service.calendarList().list().execute()
        return result.get('items', [])

    def _event_exists(self, title, start_dt):
        window_start = (start_dt - timedelta(hours=1)).isoformat()
        window_end = (start_dt + timedelta(hours=1)).isoformat()
        try:
            events = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=window_start,
                timeMax=window_end,
                q=title,
                singleEvents=True,
            ).execute()
            for e in events.get('items', []):
                if e.get('summary', '').strip() == title.strip():
                    return True
        except HttpError:
            pass
        return False

    def create_event(self, game, user_tz='America/New_York', color_id=None):
        start_utc = game['start_utc']
        end_utc = start_utc + timedelta(hours=game['duration_hours'])

        start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ') if start_utc.tzinfo else start_utc.isoformat() + 'Z'
        end_str = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ') if end_utc.tzinfo else end_utc.isoformat() + 'Z'

        title = game['title']
        if self._event_exists(title, start_utc):
            return 'exists', None

        body = {
            'summary': title,
            'description': game.get('description', ''),
            'start': {'dateTime': start_str, 'timeZone': 'UTC'},
            'end':   {'dateTime': end_str,   'timeZone': 'UTC'},
        }
        if game.get('location'):
            body['location'] = game['location']
        if color_id:
            body['colorId'] = str(color_id)

        try:
            created = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
            return 'created', created.get('htmlLink')
        except HttpError as e:
            return 'error', str(e)

    def add_schedule(self, games, user_tz='America/New_York', color_id=None):
        """
        Sync a list of games to Google Calendar efficiently.

        Strategy (avoids per-game HTTP round-trips that time out on large schedules):
          1. One bulk events.list() across the full season date range to build a
             set of already-existing event titles — replaces N individual checks.
          2. Batch inserts in groups of 50 — reduces N insert calls to ~N/50 HTTP
             requests. Critical for MLB (162 games) which previously hit Render's
             30-second request timeout.
        """
        if not games:
            return 0, 0, 0

        # ── 1. Bulk existence check (1 paginated list call) ───────────────────
        start_dts = []
        for g in games:
            dt = g.get('start_utc')
            if dt:
                if not getattr(dt, 'tzinfo', None):
                    dt = dt.replace(tzinfo=timezone.utc)
                start_dts.append(dt)

        existing_titles: set[str] = set()
        if start_dts:
            range_min = (min(start_dts) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
            range_max = (max(start_dts) + timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%SZ')
            try:
                page_token = None
                while True:
                    resp = self.service.events().list(
                        calendarId=self.calendar_id,
                        timeMin=range_min,
                        timeMax=range_max,
                        singleEvents=True,
                        maxResults=2500,
                        pageToken=page_token,
                    ).execute()
                    for ev in resp.get('items', []):
                        existing_titles.add(ev.get('summary', '').strip())
                    page_token = resp.get('nextPageToken')
                    if not page_token:
                        break
            except Exception:
                pass  # If the check fails, proceed and try inserting everything

        # ── 2. Batch inserts (50 per HTTP request) ────────────────────────────
        counters = {'created': 0, 'skipped': 0, 'errors': 0}

        def _callback(request_id, response, exception):
            if exception:
                counters['errors'] += 1
            else:
                counters['created'] += 1

        to_insert = []
        for game in games:
            if game.get('title', '').strip() in existing_titles:
                counters['skipped'] += 1
            else:
                to_insert.append(game)

        BATCH_SIZE = 50
        for i in range(0, len(to_insert), BATCH_SIZE):
            batch = self.service.new_batch_http_request(callback=_callback)
            for game in to_insert[i : i + BATCH_SIZE]:
                start_utc = game['start_utc']
                if not getattr(start_utc, 'tzinfo', None):
                    start_utc = start_utc.replace(tzinfo=timezone.utc)
                end_utc = start_utc + timedelta(hours=game['duration_hours'])
                start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                end_str   = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                body = {
                    'summary':     game['title'],
                    'description': game.get('description', ''),
                    'start': {'dateTime': start_str, 'timeZone': 'UTC'},
                    'end':   {'dateTime': end_str,   'timeZone': 'UTC'},
                }
                if game.get('location'):
                    body['location'] = game['location']
                if color_id:
                    body['colorId'] = str(color_id)
                batch.add(self.service.events().insert(
                    calendarId=self.calendar_id, body=body
                ))
            batch.execute()

        return counters['created'], counters['skipped'], counters['errors']
