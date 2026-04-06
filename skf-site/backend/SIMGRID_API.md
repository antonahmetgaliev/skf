# SimGrid API v1 Reference

**Base URL:** `https://www.thesimgrid.com/api/v1`
**Alt hosts (from community code):** `api.thesimgrid.com`, `gridos-api.thesimgrid.com`
**Auth:** Bearer token via `Authorization: Bearer {token}`

> Community sources: JanuarySnow/RRR-Bot (Python), geofffranks/rookies-bot (Go), oNiD-Community-Racing/onid-assistant (Kotlin), arelstone/simgrid-utils (TS)

---

## Brands

### List all brands
`GET /brands`

### Retrieve a brand
`GET /brands/:id`

---

## Car Classes

### List all car classes
`GET /car_classes`

### Retrieve a car class
`GET /car_classes/:id`

---

## Cars

A Car object represents a formal, specific car (make, model, variation), tied to a specific Game.

### List all cars
`GET /cars?game_id=&car_class_id=`

Params:
- `game_id` (optional)
- `car_class_id` (optional)

Response: grouped by car class ID
```json
[
  {
    "21": [
      {"id": 25, "name": "Alpine GT4", "in_game_id": 50, "in_game_name": "alpine_a110_gt4"}
    ]
  }
]
```

### Retrieve a car
`GET /cars/:id`

---

## Championship Car Classes

A ChampionshipCarClass represents a registerable car class for a given Championship.

### List all championship car classes
`GET /championships/:id/championship_car_classes`

Response:
```json
[{"id": 1308, "display_name": "GT3", "championship_id": 710, "capacity": 48}]
```

---

## Championships

The Championship object represents any events on the platform, both single events and full championships.

### List all championships
`GET /championships?limit=200&offset=0`

Response:
```json
[{
  "id": 710,
  "name": "Championship Name",
  "starts_at": "2024-01-01T19:00:00.000Z",
  "ends_at": "2024-03-01T19:00:00.000Z",
  "accepting_registrations": true,
  "event_completed": false
}]
```

### Retrieve a championship
`GET /championships/:id`

Response: full championship detail object
```json
{
  "id": 710,
  "name": "Championship Name",
  "url": "https://www.thesimgrid.com/championships/710",
  "description": "...",
  "image": "https://...",
  "start_date": "2024-01-01",
  "capacity": 48,
  "spots_taken": 32,
  "host_name": "SimGrid",
  "game_name": "Assetto Corsa Competizione",
  "accepting_registrations": true,
  "event_completed": false,
  "teams_enabled": true,
  "entry_fee_required": false,
  "entry_fee_cents": 0
}
```

### List all participating users
`GET /championships/:id/participating_users`

Response:
```json
[{
  "user_id": 117,
  "username": "killianrm",
  "first_name": "John",
  "last_name": "Doe",
  "steam64_id": "12341",
  "discord_uid": "12341",
  "psn_id": "12341",
  "xbox_id": "12341",
  "epic_id": "12341",
  "epic_username": "12341",
  "car_number": 42
}]
```

### Retrieve an entrylist
`GET /championships/:id/entrylist?format=json&championship_car_class_ids[]=`

Params:
- `format` (required): "json", "ini", or "csv"
- `championship_car_class_ids[]` (optional): filter by car class

Response (json format) — ACC-style entry data:
```json
{
  "entries": [
    {
      "drivers": [{"playerID": "S76561198172339129", "firstName": "John", "lastName": "Doe"}],
      "raceNumber": 42,
      "isServerAdmin": 1
    }
  ],
  "forceEntryList": 1
}
```

Note: `playerID` is Steam ID prefixed with "S". Response may be `{"entries": [...]}` or bare array.

### List all championship_car_classes
`GET /championships/:id/championship_car_classes`

(Same as Championship Car Classes section above)

### Standings
`GET /championships/:id/standings`

Response: array of 2 elements `[entries_array, races_array]`
- entries_array: standings entries with `position_cache`, `display_name`, `championship_points`, `championship_penalties`, `championship_score`, `partial_standings`, `participant` (with `country_code`), `championship_car_class`, `user_id`, `car`, etc.
- races_array: race metadata with `id`, `display_name`/`race_name`, `starts_at`, `results_available`, `ended`

---

## Communities

### List all communities
`GET /communities`

---

## Event Server Configs

### Retrieve an event server config
`GET /event_server_configs/:id`

---

## Games

### List all games
`GET /games`

### Retrieve a game
`GET /games/:id`

### List all tracks for a game (deprecated)
`GET /games/:id/tracks`

### List all cars for a game (deprecated)
`GET /games/:id/cars`

Response:
```json
[{"id": 15, "name": "Jaguar GT3", "in_game_id": 14, "in_game_name": "Assetto Corsa Competizione"}]
```

---

## Graphic Blocks

### List all graphic blocks
`GET /graphic_blocks`

Does not increment impressions.

Response:
```json
[{"id": 2, "title": "Introducing ACC Setup Subscriptions"}]
```

### Retrieve a graphic block
`GET /graphic_blocks/:id`

Increments impressions.

Response:
```json
{
  "id": 1,
  "admin_organization_id": 1,
  "title": "Coach Dave Academy BMW M4 GT3 Setups Available",
  "description": "...",
  "link": "https://...",
  "image": "https://...",
  "call_to_action": "buy_now",
  "brand_id": 1
}
```

### Draw a random set of graphic blocks
`GET /graphic_blocks/draw?count=1&seed=0.123456789`

Increments impressions. Use the `link` value to build a redirect link (POST via `data-method="post"`).

Params:
- `count` (optional): number of ads, defaults to 1
- `seed` (optional): 0-1.0, prevents duplicate results across requests in same session

---

## Leaderboards

### Fastest lap times
`GET /leaderboards/lap_times?track_id=128&car_id=215&filter=&user_id=&attribute=`

Params:
- `track_id` (required)
- `car_id` (optional)
- `filter` (optional): "followers"
- `user_id` (required if filtering by followers)
- `attribute` (optional): "discord" to find user by Discord ID

Response:
```json
[{"user_id": 35636, "track_id": 128, "car_id": 215, "lap_time": 125697}]
```

---

## Liveries

### Update a livery
`PATCH /liveries/:id`

### Delete a livery
`DELETE /liveries/:id`

---

## Race Server Configs

### Retrieve a race server config
`GET /race_server_configs/:id`

---

## Race Signouts

### List all race signouts
`GET /race_signouts`

---

## Races

### List all races
`GET /races?championship_id=:id`

Response:
```json
[{
  "id": 261,
  "display_name": "Race Name",
  "starts_at": "2024-01-15T19:00:00.000Z",
  "track": {"name": "Nurburgring"},
  "results_available": true,
  "ended": true
}]
```

Note: `track` can be a dict `{"name": "..."}` or a plain string.

### Retrieve a race
`GET /races/:id`

### Retrieve an Entrylist
`GET /races/:id/entrylist`

### Import results (coming soon)
`POST /races/:id/import_results`

---

## Registrations

### List all registrations
`GET /registrations`

### Retrieve a registration
`GET /registrations/:id`

---

## Rounds

### List all rounds
`GET /rounds`

### Retrieve a round
`GET /rounds/:id`

---

## Seasons

A Season object is used solely for daily racing. A Season can contain multiple Championships.

### List all seasons
`GET /seasons`

### Retrieve a season
`GET /seasons/:id`

---

## Sponsors

### List all sponsors
`GET /sponsors`

---

## Teams

A Team object represents a group of drivers who race together.

### List all teams
`GET /teams`

Response:
```json
[{
  "team_id": 1,
  "name": "Super Fast People",
  "total_races_started": null,
  "total_wins": null,
  "total_podiums": null,
  "total_penalty_rate": null
}]
```

### Retrieve a team
`GET /teams/:id`

---

## Tracks

A Track object represents a track for a specific Game.

### List all tracks
`GET /tracks?game_id=1`

Params:
- `game_id` (optional)

Response:
```json
[{
  "id": 1,
  "game_id": 1,
  "name": "Barcelona",
  "in_game_name": "barcelona",
  "photo": "https://...",
  "parent_track_id": null,
  "external_data": null
}]
```

---

## Users

### List all users
`GET /users`

### Retrieve a user
`GET /users/:id`
`GET /users/:id?attribute=discord` — lookup by Discord ID instead of SimGrid user ID

Response:
```json
{
  "user_id": 117,
  "username": "killianrm",
  "preferred_name": "Killian",
  "steam64_id": "76561198172339129",
  "discord_uid": "123456789",
  "teams": [{"id": 1, "name": "Team Name"}],
  "total_races_started": 42,
  "total_wins": 5,
  "total_podiums": 12,
  "simgrid_pro_active": true,
  "boosted_hosts": [],
  "grid_ratings": [{"game_id": 1, "rating": 1500}]
}
```

### List a user's races
`GET /users/:user_id/races?filter=&limit=&exclude_dsq=`

Params:
- `filter` (optional): "upcoming" for upcoming only
- `limit` (optional): integer
- `exclude_dsq` (optional): defaults to true

Response:
```json
[{
  "id": 261,
  "race_name": "",
  "track": "Nurburgring",
  "starts_at": "2020-11-12T19:30:00.000Z",
  "host_name": "SimGrid",
  "championship_id": 160,
  "championship_name": "Rain Meister",
  "game_name": "Assetto Corsa Competizione",
  "platform": "PC",
  "car": "Mercedes-AMG GT3"
}]
```

### Set user status
`POST /users/:user_id/set_status?status=in_game&track_id=128&car_id=215`

Params:
- `status` (required): "inactive" or "in_game"
- `track_id` (optional): used when setting status as "in_game"
- `car_id` (optional): used when setting status as "in_game"

---

## Admin/Web URLs (not REST API)

These use the web interface, not the `/api/v1` prefix:

- `GET /admin/championships/:id/registrations.{json|csv}` — Export registrations
- `GET /admin/championships/:id/team_registrations.{json|csv}` — Export team registrations
