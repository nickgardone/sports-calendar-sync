# Sports Calendar — Setup Guide

## 1. Install Python dependencies

```bash
cd sports-calendar
pip install -r requirements.txt
```

## 2. Create Google Cloud credentials

This tool needs access to your Google Calendar. Do this once:

1. Go to https://console.cloud.google.com/
2. Create a new project (or use an existing one) — name it anything, e.g. "Sports Calendar"
3. In the left sidebar: **APIs & Services → Library**
4. Search for **Google Calendar API** and click **Enable**
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → OAuth client ID**
7. If prompted, configure the OAuth consent screen:
   - User type: **External**
   - App name: "Sports Calendar"
   - Add your email as a test user
8. Back in Create OAuth client ID:
   - Application type: **Desktop app**
   - Name: "Sports Calendar"
9. Click **Create**, then **Download JSON**
10. Rename the downloaded file to `credentials.json` and place it in this `sports-calendar/` folder

## 3. Authorize the app (first run only)

The first time you run the tool, a browser window will open asking you to sign in with Google and grant calendar access. After you approve, a `token.json` file is saved locally so you won't need to authorize again.

## 4. Run the tool

```bash
# Team-based sports — specify your team
python main.py "San Francisco 49ers"
python main.py "Lakers" --league NBA
python main.py "New York Rangers" --league NHL
python main.py "Chicago Cubs" --league MLB
python main.py "Portland Timbers" --league MLS
python main.py "Las Vegas Aces" --league WNBA

# Non-team sports — no team name needed, just the league
python main.py --league PGA       # All PGA Tour tournaments
python main.py --league NASCAR    # All NASCAR Cup Series races
python main.py --league UFC       # All UFC events

# Specify a timezone explicitly (otherwise auto-detected from your Mac)
python main.py "49ers" --timezone America/Chicago

# Add to a specific calendar instead of primary
python main.py --list-calendars              # see your calendars and their IDs
python main.py "49ers" --calendar "Sports"  # use display name or calendar ID
```

## Notes

- **Home games** show as: `San Francisco 49ers vs. Dallas Cowboys`
- **Away games** show as: `San Francisco 49ers @ Dallas Cowboys`
- Game times are stored in UTC and displayed in your local timezone by Google Calendar automatically
- Re-running the tool won't create duplicate events (existing events are detected and skipped)
- If the schedule isn't published yet, the tool will tell you and exit cleanly
- `token.json` and `credentials.json` contain sensitive data — don't share or commit them
