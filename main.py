#!/usr/bin/env python3
"""
sports-calendar: Add a sports team's schedule to Google Calendar.

Usage:
  python main.py "San Francisco 49ers"
  python main.py "Lakers" --league NBA
  python main.py "Chicago Blackhawks" --league NHL --calendar "Sports"
  python main.py --league PGA          # All PGA Tour events (non-team sport)
  python main.py --league NASCAR       # All NASCAR Cup races
  python main.py --league UFC          # All UFC events
"""

import argparse
import sys
import os

from leagues import LEAGUE_CONFIG, LEAGUE_ALIASES
from espn_client import ESPNClient
from google_calendar import GoogleCalendarClient


def resolve_league(raw):
    """Normalize league string to a LEAGUE_CONFIG key."""
    if not raw:
        return None
    upper = raw.upper().strip()
    if upper in LEAGUE_CONFIG:
        return upper
    if upper in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[upper]
    return None


def pick_team(matches, query):
    """If multiple teams match, prompt the user to pick one."""
    if len(matches) == 1:
        return matches[0]

    print(f"\nMultiple teams match '{query}':")
    for i, t in enumerate(matches, 1):
        print(f"  {i}. {t['name']} ({t['league']})")
    while True:
        try:
            choice = int(input("\nEnter number: ").strip())
            if 1 <= choice <= len(matches):
                return matches[choice - 1]
        except (ValueError, KeyboardInterrupt):
            pass
        print(f"  Please enter a number between 1 and {len(matches)}.")


def get_user_timezone():
    """Best-effort local timezone detection."""
    try:
        import subprocess
        result = subprocess.run(['systemsetup', '-gettimezone'], capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.strip().split(': ')
            if len(parts) == 2:
                return parts[1]
    except Exception:
        pass

    tz_env = os.environ.get('TZ')
    if tz_env:
        return tz_env

    try:
        link = os.readlink('/etc/localtime')
        # /usr/share/zoneinfo/America/New_York
        idx = link.find('zoneinfo/')
        if idx != -1:
            return link[idx + len('zoneinfo/'):]
    except Exception:
        pass

    return 'America/New_York'


def run_team_sport(espn, gcal, team_query, league_key, user_tz):
    print(f"\nSearching for '{team_query}'" + (f" in {league_key}" if league_key else " across all leagues") + "...")
    matches = espn.search_teams(team_query, league_key)

    if not matches:
        leagues_tried = league_key or "NFL, NBA, MLB, NHL, MLS, WNBA"
        print(f"\nNo team found matching '{team_query}' in {leagues_tried}.")
        print("Tips:")
        print("  - Try a partial name: 'Lakers', '49ers', 'Yankees'")
        print("  - Specify --league to narrow the search")
        sys.exit(1)

    team = pick_team(matches, team_query)
    league_key = team['league']
    print(f"\nFound: {team['name']} ({league_key})")

    print(f"Fetching schedule...")
    events, season_year = espn.get_team_schedule(team['id'], league_key)

    if not events:
        print(f"\nSchedule not yet available for the {team['name']}.")
        print("The schedule may not have been released yet — check back closer to the season start.")
        sys.exit(0)

    print(f"Found {len(events)} games for the {season_year} season.")

    games = []
    for event in events:
        game = espn.parse_team_game(event, team['id'], team['name'], league_key)
        if game:
            games.append(game)

    if not games:
        print("Could not parse any games from the schedule.")
        sys.exit(1)

    # Filter to future + in-progress only (skip completed games if desired)
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    future_games = [g for g in games if g['start_utc'] > now]
    past_games = [g for g in games if g['start_utc'] <= now]

    print(f"  {len(future_games)} upcoming, {len(past_games)} already played")

    all_games = past_games + future_games
    total = len(all_games)

    print(f"\nAdding {total} events to Google Calendar (timezone: {user_tz})...")
    created, skipped, errors = gcal.add_schedule(all_games, user_tz)

    _print_summary(created, skipped, errors, total)


def run_event_sport(espn, gcal, league_key, user_tz):
    sport_name = {
        'PGA': 'PGA Tour',
        'NASCAR': 'NASCAR Cup Series',
        'UFC': 'UFC',
    }.get(league_key, league_key)

    print(f"\nFetching {sport_name} schedule...")
    events = espn.get_event_schedule(league_key)

    if not events:
        print(f"\nSchedule not yet available for {sport_name}.")
        print("The schedule may not have been published yet — check back later.")
        sys.exit(0)

    print(f"Found {len(events)} events.")

    games = []
    for event in events:
        game = espn.parse_event_game(event, league_key)
        if game:
            games.append(game)

    if not games:
        print("Could not parse any events from the schedule.")
        sys.exit(1)

    print(f"\nAdding {len(games)} events to Google Calendar (timezone: {user_tz})...")
    created, skipped, errors = gcal.add_schedule(games, user_tz)

    _print_summary(created, skipped, errors, len(games))


def _print_summary(created, skipped, errors, total):
    print(f"\nDone.")
    print(f"  Created: {created}")
    if skipped:
        print(f"  Already existed (skipped): {skipped}")
    if errors:
        print(f"  Errors: {errors}")


def main():
    parser = argparse.ArgumentParser(
        description="Add a sports team's schedule to Google Calendar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "San Francisco 49ers"
  python main.py "Lakers" --league NBA
  python main.py "New York Rangers" --league NHL --calendar primary
  python main.py --league PGA
  python main.py --league NASCAR
  python main.py --league UFC

Non-team sports (PGA, NASCAR, UFC) don't need a team name — just pass --league.
        """
    )
    parser.add_argument('team', nargs='?', help='Team name or partial name')
    parser.add_argument('--league', '-l', help='League: NFL, NBA, MLB, NHL, MLS, WNBA, PGA, NASCAR, UFC')
    parser.add_argument('--calendar', '-c', default='primary', help='Google Calendar ID (default: primary)')
    parser.add_argument('--timezone', '-tz', default=None,
                        help='Your timezone, e.g. America/Chicago (auto-detected if omitted)')
    parser.add_argument('--list-calendars', action='store_true', help='List available Google Calendars and exit')

    args = parser.parse_args()

    league_key = resolve_league(args.league)
    if args.league and not league_key:
        print(f"Unknown league '{args.league}'. Supported: NFL, NBA, MLB, NHL, MLS, WNBA, PGA, NASCAR, UFC")
        sys.exit(1)

    user_tz = args.timezone or get_user_timezone()

    try:
        gcal = GoogleCalendarClient(args.calendar)
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        print("See SETUP.md for how to create your Google credentials.")
        sys.exit(1)

    if args.list_calendars:
        calendars = gcal.list_calendars()
        print("\nYour Google Calendars:")
        for cal in calendars:
            print(f"  {cal['summary']:<35}  id: {cal['id']}")
        sys.exit(0)

    espn = ESPNClient()

    # Non-team sports need only a league
    if league_key and not LEAGUE_CONFIG[league_key]['team_based']:
        if args.team:
            print(f"Note: {league_key} is not team-based — ignoring team name and fetching full schedule.")
        run_event_sport(espn, gcal, league_key, user_tz)
        return

    # Team-based sports require a team name
    if not args.team:
        parser.print_help()
        print("\nError: a team name is required for team-based sports (NFL, NBA, MLB, NHL, MLS, WNBA).")
        sys.exit(1)

    run_team_sport(espn, gcal, args.team, league_key, user_tz)


if __name__ == '__main__':
    main()
