LEAGUE_CONFIG = {
    'NFL': {
        'sport': 'football',
        'league': 'nfl',
        'duration_hours': 3.5,
        'team_based': True,
    },
    'NBA': {
        'sport': 'basketball',
        'league': 'nba',
        'duration_hours': 2.5,
        'team_based': True,
    },
    'MLB': {
        'sport': 'baseball',
        'league': 'mlb',
        'duration_hours': 3.0,
        'team_based': True,
    },
    'NHL': {
        'sport': 'hockey',
        'league': 'nhl',
        'duration_hours': 2.5,
        'team_based': True,
    },
    'MLS': {
        'sport': 'soccer',
        'league': 'usa.1',
        'duration_hours': 2.0,
        'team_based': True,
    },
    'WNBA': {
        'sport': 'basketball',
        'league': 'wnba',
        'duration_hours': 2.5,
        'team_based': True,
    },
    'PGA': {
        'sport': 'golf',
        'league': 'pga',
        'duration_hours': 8.0,
        'team_based': False,
        # PGA events are multi-day tournaments; each round is 1 all-day block
    },
    'NASCAR': {
        'sport': 'racing',
        'league': 'nascar-premier',
        'duration_hours': 4.0,
        'team_based': False,
    },
    'UFC': {
        'sport': 'mma',
        'league': 'ufc',
        'duration_hours': 5.0,
        'team_based': False,
    },
}

LEAGUE_ALIASES = {
    'FOOTBALL': 'NFL',
    'BASKETBALL': 'NBA',
    'HOCKEY': 'NHL',
    'BASEBALL': 'MLB',
    'SOCCER': 'MLS',
    'GOLF': 'PGA',
    'PGA TOUR': 'PGA',
    'RACING': 'NASCAR',
    'CUP SERIES': 'NASCAR',
    'MMA': 'UFC',
    'MIXED MARTIAL ARTS': 'UFC',
    "WOMEN'S BASKETBALL": 'WNBA',
    'WOMENS BASKETBALL': 'WNBA',
}
