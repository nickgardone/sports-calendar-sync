import os
import pickle
from datetime import timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_FILE = Path(__file__).parent / 'token.json'
CREDENTIALS_FILE = Path(__file__).parent / 'credentials.json'


class GoogleCalendarClient:
    def __init__(self, calendar_id='primary'):
        self.calendar_id = calendar_id
        self.service = self._authenticate()

    def _authenticate(self):
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Missing credentials.json — see SETUP.md for instructions to create one."
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
        """Check whether an identical event already exists on this date."""
        # Search ±1 day window around the event start
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

    def create_event(self, game, user_tz='America/New_York'):
        """
        Create a single Google Calendar event from a parsed game dict.
        Returns ('created', event_link) | ('exists', None) | ('error', msg)
        """
        start_utc = game['start_utc']
        end_utc = start_utc + timedelta(hours=game['duration_hours'])

        # Format as RFC3339 with UTC offset
        start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ') if start_utc.tzinfo else start_utc.isoformat() + 'Z'
        end_str = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ') if end_utc.tzinfo else end_utc.isoformat() + 'Z'

        title = game['title']

        if self._event_exists(title, start_utc):
            return 'exists', None

        body = {
            'summary': title,
            'description': game.get('description', ''),
            'start': {
                'dateTime': start_str,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_str,
                'timeZone': 'UTC',
            },
        }

        if game.get('location'):
            body['location'] = game['location']

        try:
            created = self.service.events().insert(
                calendarId=self.calendar_id, body=body
            ).execute()
            return 'created', created.get('htmlLink')
        except HttpError as e:
            return 'error', str(e)

    def add_schedule(self, games, user_tz='America/New_York'):
        """
        Add all games to Google Calendar.
        Returns (created_count, skipped_count, error_count).
        """
        created = skipped = errors = 0
        total = len(games)

        for i, game in enumerate(games, 1):
            status, detail = self.create_event(game, user_tz)
            if status == 'created':
                created += 1
                date_str = game['start_utc'].strftime('%b %-d')
                print(f"  [{i}/{total}] Added: {game['title']} ({date_str})")
            elif status == 'exists':
                skipped += 1
            else:
                errors += 1
                print(f"  [{i}/{total}] Error adding {game['title']}: {detail}")

        return created, skipped, errors
