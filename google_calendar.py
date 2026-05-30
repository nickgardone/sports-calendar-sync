import os
from datetime import timedelta
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
        created = skipped = errors = 0
        for game in games:
            status, _ = self.create_event(game, user_tz, color_id=color_id)
            if status == 'created':
                created += 1
            elif status == 'exists':
                skipped += 1
            else:
                errors += 1
        return created, skipped, errors
