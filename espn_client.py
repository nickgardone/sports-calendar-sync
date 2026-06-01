import requests
from datetime import datetime
from leagues import LEAGUE_CONFIG

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"


class ESPNClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'sports-calendar/1.0'})

    def _get(self, url, params=None):
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            print(f"  Request failed for {url}: {e}")
            return None

    def search_teams(self, query, league_key=None):
        """Return list of matching team dicts across one or all team-based leagues."""
        leagues_to_search = [league_key] if league_key else [
            k for k, v in LEAGUE_CONFIG.items() if v['team_based']
        ]
        results = []
        q = query.lower().strip()

        for lk in leagues_to_search:
            cfg = LEAGUE_CONFIG[lk]
            url = f"{ESPN_BASE}/{cfg['sport']}/{cfg['league']}/teams"
            data = self._get(url, params={'limit': 200})
            if not data:
                continue

            # ESPN wraps teams under sports > leagues > teams
            raw_teams = []
            for sport_block in data.get('sports', []):
                for league_block in sport_block.get('leagues', []):
                    raw_teams.extend(league_block.get('teams', []))
            # Some endpoints return a top-level teams array
            if not raw_teams:
                raw_teams = data.get('teams', [])

            for wrapper in raw_teams:
                team = wrapper.get('team', wrapper)
                fields = [
                    team.get('displayName', '').lower(),
                    team.get('shortDisplayName', '').lower(),
                    team.get('name', '').lower(),
                    team.get('abbreviation', '').lower(),
                    team.get('location', '').lower(),
                ]
                if any(q in f for f in fields):
                    results.append({
                        'id': team.get('id'),
                        'name': team.get('displayName', team.get('name', 'Unknown')),
                        'abbreviation': team.get('abbreviation', ''),
                        'league': lk,
                        'sport': cfg['sport'],
                        'league_slug': cfg['league'],
                    })

        return results

    def list_teams(self, league_key):
        """Return all teams for a team-based league, sorted alphabetically by name."""
        cfg = LEAGUE_CONFIG.get(league_key)
        if not cfg or not cfg.get('team_based'):
            return []

        url = f"{ESPN_BASE}/{cfg['sport']}/{cfg['league']}/teams"
        data = self._get(url, params={'limit': 200})
        if not data:
            return []

        raw_teams = []
        for sport_block in data.get('sports', []):
            for league_block in sport_block.get('leagues', []):
                raw_teams.extend(league_block.get('teams', []))
        if not raw_teams:
            raw_teams = data.get('teams', [])

        teams = []
        for wrapper in raw_teams:
            team = wrapper.get('team', wrapper)
            teams.append({
                'id': team.get('id'),
                'name': team.get('displayName', team.get('name', 'Unknown')),
                'league': league_key,
            })

        return sorted(teams, key=lambda t: t['name'])

    def get_team_schedule(self, team_id, league_key, season=None):
        """Fetch schedule events for a team. Returns (events, season_year) or ([], None).

        If `season` is provided (e.g. from a locked Apple Calendar subscription URL),
        only that specific year is tried — no auto-advance to the next season.
        Without a lock, tries current year then next; never falls back to previous.
        """
        cfg = LEAGUE_CONFIG[league_key]
        url = f"{ESPN_BASE}/{cfg['sport']}/{cfg['league']}/teams/{team_id}/schedule"
        now = datetime.now()
        year = now.year

        years_to_try = [int(season)] if season else [year, year + 1]

        for season_year in years_to_try:
            data = self._get(url, params={'season': season_year})
            if data is None:
                continue
            events = data.get('events', [])
            if events:
                return events, season_year

        return [], None

    def get_event_schedule(self, league_key):
        """
        For non-team sports (PGA, NASCAR, UFC): return season-level events.
        Scoreboard only shows the current/next event; we page through weekly
        calendar dates to collect the full season for PGA and NASCAR.
        """
        cfg = LEAGUE_CONFIG[league_key]
        sport = cfg['sport']
        league = cfg['league']
        url = f"{ESPN_BASE}/{sport}/{league}/scoreboard"

        if league_key in ('PGA', 'NASCAR'):
            return self._fetch_full_season_scoreboard(url)

        # UFC and others: single scoreboard call is sufficient
        data = self._get(url, params={'limit': 100})
        if data:
            return data.get('events', [])
        return []

    def _fetch_full_season_scoreboard(self, url):
        """
        Step through dates week-by-week for the current calendar year to collect
        all events from a scoreboard endpoint that only returns one event at a time.
        """
        from datetime import timedelta

        now = datetime.now()
        season_start = datetime(now.year, 1, 1)
        season_end = datetime(now.year, 12, 31)

        seen_ids = set()
        events = []
        current = season_start

        while current <= season_end:
            date_str = current.strftime('%Y%m%d')
            data = self._get(url, params={'dates': date_str})
            if data:
                for ev in data.get('events', []):
                    eid = ev.get('id')
                    if eid and eid not in seen_ids:
                        seen_ids.add(eid)
                        events.append(ev)
            current += timedelta(weeks=1)

        return events

    def parse_team_game(self, event, team_id, team_name, league_key):
        """
        Convert an ESPN event dict into a structured game dict for calendar creation.
        Returns None if the event can't be parsed.
        """
        cfg = LEAGUE_CONFIG[league_key]
        competition = event.get('competitions', [{}])[0]
        date_str = event.get('date') or competition.get('date')
        if not date_str:
            return None

        game_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))

        competitors = competition.get('competitors', [])
        home = next((c for c in competitors if c.get('homeAway') == 'home'), None)
        away = next((c for c in competitors if c.get('homeAway') == 'away'), None)

        if not home or not away:
            # Can't determine home/away — use first two competitors
            if len(competitors) >= 2:
                home, away = competitors[0], competitors[1]
            else:
                return None

        home_team = home.get('team', {})
        away_team = away.get('team', {})
        home_name = home_team.get('displayName', 'Home Team')
        away_name = away_team.get('displayName', 'Away Team')
        home_id = str(home_team.get('id', ''))

        is_home = home_id == str(team_id)
        opponent = away_name if is_home else home_name
        abbr = team_name.split()[-1]  # last word as short name for title

        if is_home:
            title = f"{team_name} vs. {opponent}"
        else:
            title = f"{team_name} @ {opponent}"

        venue = competition.get('venue', {})
        location = _build_location(venue)

        status_state = competition.get('status', {}).get('type', {}).get('state', 'pre')
        notes = competition.get('notes', [])
        note_text = notes[0].get('headline', '') if notes else ''

        description_parts = [f"{league_key} {'Home' if is_home else 'Away'} Game"]
        if note_text:
            description_parts.append(note_text)

        return {
            'title': title,
            'start_utc': game_dt,
            'duration_hours': cfg['duration_hours'],
            'location': location,
            'league': league_key,
            'is_home': is_home,
            'status': status_state,
            'description': '\n'.join(description_parts),
        }

    def parse_event_game(self, event, league_key):
        """
        For non-team sports: parse a single event (tournament/race/fight card).
        """
        cfg = LEAGUE_CONFIG[league_key]
        date_str = event.get('date')
        if not date_str:
            return None

        game_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        name = event.get('name', event.get('shortName', league_key + ' Event'))

        competition = event.get('competitions', [{}])[0] if event.get('competitions') else {}
        venue = competition.get('venue', {})
        location = _build_location(venue)

        return {
            'title': name,
            'start_utc': game_dt,
            'duration_hours': cfg['duration_hours'],
            'location': location,
            'league': league_key,
            'is_home': None,
            'status': competition.get('status', {}).get('type', {}).get('state', 'pre'),
            'description': f"{league_key} Event",
        }


def _build_location(venue):
    if not venue:
        return ''
    name = venue.get('fullName', '')
    addr = venue.get('address', {})
    city = addr.get('city', '')
    state = addr.get('state', '')
    parts = [p for p in [name, city, state] if p]
    return ', '.join(parts)
