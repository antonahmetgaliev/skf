# SimGrid API v1 Reference

Code paths below are relative to `backend/`.

**Base URL:** `https://www.thesimgrid.com/api/v1`
**Auth:** `Authorization: Bearer {token}` (`SIMGRID_API_KEY`)
**Official docs:** <https://gridos.thesimgrid.com/docs/> (Scalar); the raw spec
is <https://gridos.thesimgrid.com/openapi.yml>, pinned in `simgrid/openapi.yml`.

Everything below was re-verified against the live API and the official
OpenAPI spec on **2026-09-29**. Where our behaviour differs from the official
docs, the verified behaviour wins and the difference is called out.

---

## Read this first

### Race results: `session_results` (since 2026-09-28)

`GET /races/:id/session_results?session_type=race_1|qualifying&result_type=results`
returns the full classification per session; used by
`app/services/championship_results.py`. **`result_type` is required** — without
it `data` is `null`. `result_type=laps` returns per-lap data in `session_laps`
(time, sectors, position, tyres, fuel, `valid`); `result_type=incidents` is
empty for our races. `data` stays `null` until SimGrid publishes the results.

Each result carries `position_cache` (**position within the car class**),
`lap_count`, `best_lap` / `total_time` (ms), `points_total`,
`total_time_penalty` (s), `fastest_lap`, `dns`, `grid_rating_change`,
`sessionable.user_id` and `championship_car_class_id`. Pitfalls:

- `dnf` is never set, not even for retirements. LMU results have
  `external_data.rfactor.status` (`Finished Normally` / `DNF` / `DQ`) plus
  `finished` (overall), `class_fn`, `starting`, `class_st`; iRacing results
  have none of it, so a retirement there is indistinguishable from a car
  several laps down.
- In qualifying `position_cache` can be wrong (a driver without a timed lap
  on pole), so we rank qualifying by best lap.
- Standings' `partial_standings` are still `[]`: per-round columns in our
  standings are built from `session_results` instead.

The old scraper (`simgrid_scraper.py`, removed in `6079edc`) is not needed any
more; the SimGrid results pages are still Cloudflare-protected. The giveaway
still sources laps from the game server's result files
(`app/services/race_import.py`, parsers in `app/services/race_files/`).

### Rate limiting is real and low

SimGrid answers `429 {"error":"Minute rate limit exceeded"}`, measured at
roughly **20 requests per minute**. There is no documented quota header.

All outbound calls go through `SimgridService._get`, which bounds concurrency
with a semaphore and retries a 429 once after honouring `Retry-After`. Any
per-driver fan-out will trip the limit — design around the cache instead.

### Collections are wrapped (since 2026-09-28)

Every endpoint returning a collection answers
`{"data": [...], "pagination": {"limit", "offset", "total_count"} | null}`;
single resources are returned bare. Before this change collections were bare
arrays, and the switch silently emptied our championships list.

### Contract checks

- **Spec drift:** `python scripts/check_simgrid_spec.py` diffs the live spec
  against the pinned copy and exits 1 on any change; `--update` re-pins it.
- **Typed payloads:** `app/schemas/simgrid_raw.py` models the fields we read.
  The spec types every body as a bare `object`, which is why we don't generate
  a client from it. Collections are validated as `Envelope[...]`; a shape
  mismatch raises (and falls back to stale cache) instead of becoming `[]`.
- **Tests:** `tests/test_simgrid_contract.py` runs the models over recorded,
  anonymised payloads in `tests/fixtures/simgrid/`. `RUN_SIMGRID_LIVE=1`
  also checks them against the live API. Re-record fixtures after a spec change.

### Pagination traps

- `/races` takes `limit` only (no `offset`); its default of 10 would silently
  truncate round lists.
- `/championships/:id/standings` pages with `page`/`per_page` (40 per page by
  default), not `limit`/`offset`.

Paginated collections default to `limit=10` (cap 500). `/races` ignores
`offset`, so we request `limit=100`.

### Alternate hosts do not exist

`api.thesimgrid.com` and `gridos-api.thesimgrid.com` appear in some community
code. Neither resolves in DNS. Use `www.thesimgrid.com`.

---

## Championships

### List championships
`GET /championships?limit=200&offset=0`

Returns **only** `id` and `name` — no dates, no status. Scoped to the token's
host (ours sees ~10 SKF championships, not the whole platform). Dates and
registration state come from the detail endpoint
(`SimgridService.with_details`, applied to active championships only).

```json
{"data": [{"id": 26927, "name": "SKF LMU Hyper 70"}],
 "pagination": {"limit": 200, "offset": 0, "total_count": 9}}
```

Official docs list further params (`status`, `driver`, `grid`, `order_by`,
`seasons`, `priority_sort`, `races_count`); we use none of them.

### Retrieve a championship
`GET /championships/:id`

Note `start_date`/`end_date` (not `starts_at`/`ends_at`). There is no
`description` and no `event_completed`. `races[]` is embedded, each race
carrying a full `track` object.

```json
{
  "id": 21950,
  "name": "SKF LMU Euro Clash",
  "url": "https://www.thesimgrid.com/championships/21950",
  "results_url": "https://www.thesimgrid.com/championships/21950/results",
  "start_date": "2026-02-28T17:00:00.000Z",
  "end_date": null,
  "capacity": 38,
  "spots_taken": 23,
  "host_name": "SKF Racing Hub",
  "game_name": "Le Mans Ultimate",
  "round_number": null,
  "all_rounds_number": 0,
  "accepting_registrations": true,
  "races": [{ "id": 165901, "race_name": "Euro Clash - Round 1", "track": {"name": "Silverstone (ELMS)"} }]
}
```

### Standings
`GET /championships/:id/standings` (+ `?filter_class={ccid}`, `&page=N`)

Relied on by `SimgridService.get_standings`.

`{"data": entries, "pagination": {...}, "completed_races": races,
"standings": ..., "is_series": bool}`. Pages via `page` (40 per page by
default, `per_page` up to 500); `offset` is ignored. Without `filter_class`
only the first car class is returned. (Until 2026-09-28 this was a
heterogeneous array `[entries, races, null, {pagination}]`; the parser still
accepts both.)

```json
{
  "id": 999087,               // registration id — NOT the driver
  "user_id": 75640,           // the driver; use this to link
  "position_cache": 1,
  "display_name": "Anatolii Maksimyuk",
  "championship_points": 50.0,
  "championship_penalties": 0,
  "championship_score": 50.0,
  "car": "Aston Martin Valkyrie LMH",
  "class": "Hypercar",
  "championship_car_class": { "display_name": "Hypercar" },
  "participant": { "country_code": "UA", "grid_rating": {"score": 2257} },
  "partial_standings": []     // ALWAYS EMPTY
}
```

There is no DSQ flag in the payload.

### Participating users
`GET /championships/:id/participating_users`

Everyone **registered** — not everyone who raced. Returns `user_id`,
`username`, `first_name`, `last_name`, `steam64_id`, `discord_uid`,
`car_number`.

### Registrations
`GET /registrations?registerable_type=Championship&registerable_id=:id`
`GET /championships/:id/registrations`

Both forms work and return the same shape — the first is the documented one,
the second an undocumented convenience. Returns registration id, `user_id`,
`registerable_*` and `championship_car_class`. Note `?championship_id=` is
*not* a valid filter on `/registrations` and answers `404`.

### Car classes / entrylist
`GET /championships/:id/championship_car_classes` →
`[{"id": 1308, "display_name": "GT3", "championship_id": 710, "capacity": 48}]`

`GET /championships/:id/entrylist?format=json|ini|csv` → ACC-style entry data.
`playerID` is a Steam ID prefixed with `S`.

---

## Races

### List races
`GET /races?championship_id=:id&limit=100`

`data` items:

```json
[{
  "id": 165904,
  "race_name": "Euro Clash - Round 4",
  "display_name": "Euro Clash - Round 4",
  "starts_at": "2026-03-21T17:00:00.000Z",
  "track": {"id": 3290, "name": "Spa-Francorchamps (WEC)", "in_game_name": "SpaWEC"},
  "results_available": true,
  "ended": true,
  "published_at": "2026-03-23T21:06:36.258Z",
  "championship_id": 21950,
  "game_name": "Le Mans Ultimate",
  "provisional_results": false
}]
```

`track` may be a dict or a plain string.

### List the races one driver actually took part in
`GET /races?user_id=:id`

**The single most useful undocumented detail on this page.**

- `GET /users/:id/races` — the form our old docs described, and the one in the
  official collection — returns **404**. Do not use it.
- `user_id` works on `/races`, but **only without `championship_id`**. Passing
  both makes `user_id` silently ignored and returns the full round list: a
  nonexistent `user_id` still came back with every race of the championship.
  Filter by `championship_id` client-side instead.

It reflects **participation, not registration** — verified against championship
25804: a driver holding 26 championship points appeared with only 1 of the 5
rounds, while another with 0 points appeared with all 5.

Fields: `id`, `race_name`, `track`, `starts_at`, `ended`, `results_available`,
`championship_id`, `championship_name`, `game_name`, `platform`, `car`.
**No laps and no finishing position.**

### Other race endpoints
- `GET /races/:id` — metadata only.
- `GET /races/:id/entrylist` — pre-race entries (`playerID` only; no names).
- `GET /races/:id/session_results` — see *Race results* above.
- `POST /races/:id/import_results` — in the collection; returns `404` for us.

---

## Users

### Retrieve a user
`GET /users/:id` — also `?attribute=discord` to look up by Discord ID, which is
how `app/services/drivers.py` finds the driver of an account at sign-in. The
sync stores `discord_uid` and `steam64_id` from `participating_users` on each
driver and links accounts from there.

```json
{
  "user_id": 75640,
  "username": "menly1ss",
  "preferred_name": "Anatolii Maksimyuk",
  "steam64_id": "76561199185293124",
  "discord_uid": "797855508676870165",
  "teams": [{"team_id": 13424, "name": "Ukraine Esport Team"}],
  "total_races_started": 19,
  "total_wins": 2,
  "total_podiums": 5,
  "grid_ratings": [{"game_id": 1, "score": 2051, "score_name": "bronze"}]
}
```

`total_races_started` counts platform-wide and will exceed what
`races?user_id=` returns, since that is scoped to what the token can see.

### Set status
`POST /users/:user_id/set_status?status=in_game&track_id=&car_id=`

---

## Reference data

| Endpoint | Notes |
|---|---|
| `GET /games`, `GET /games/:id` | |
| `GET /tracks?game_id=` | |
| `GET /cars?game_id=&car_class_id=` | response is grouped by car class id |
| `GET /cars/:id`, `GET /car_classes`, `GET /car_classes/:id` | |
| `GET /brands`, `GET /brands/:id` | |
| `GET /communities?limit=&offset=` | |
| `GET /teams`, `GET /teams/:id` | |
| `GET /seasons?limit=&user_id=`, `GET /seasons/:id` | daily racing only |
| `GET /rounds?limit=&championship_id=&user_id=`, `GET /rounds/:id` | a scheduling construct, not a results one |
| `GET /leaderboards/lap_times?track_id=&car_id=` | fastest laps; `track_id` required |
| `GET /race_signouts?race_id=` | |
| `GET /race_server_configs/:id`, `GET /event_server_configs/:race_id` | |
| `GET /sponsors`, `GET /graphic_blocks`, `GET /graphic_blocks/draw` | advertising |
| `PATCH`/`DELETE /liveries/:id` | |

`GET /games/:id/tracks` and `GET /games/:id/cars` are deprecated in favour of
the top-level `tracks`/`cars` endpoints.

---

## What we actually call

All SimGrid traffic is server-side, in `app/services/simgrid.py`. The frontend
talks only to our own `/api/v1/championships/*`.

| Method | Endpoint | Cache key | TTL |
|---|---|---|---|
| `get_championships` | `/championships` (paged) | `championships_list_{limit}` | 1 day |
| `get_championship` | `/championships/{id}` | `championship_{id}` | 1 day |
| `get_races` | `/races?championship_id=&limit=100` | `races_{id}` | 1 day |
| `get_standings` | `/championships/{id}/standings` (+ per class, paged) | `standings_{id}` | 1 hour |
| `get_participating_users` | `/championships/{id}/participating_users` | `participants_{id}` | 10 min |
| `get_user_by_discord_id` | `/users/{uid}?attribute=discord` | `user_by_discord_{uid}` | 10 min |
| `get_race_name` | `/races/{id}` | — | none |
| `get_games` / `get_car_classes` | `/games`, `/car_classes` | `games_list`, `car_classes*` | 1 day |
| `_championship_car_class_ids` | `/championships/{id}/championship_car_classes` | — | none |
| `get_session_results` | `/races/{id}/session_results?session_type=&result_type=results` | `session_results_{cid}_{rid}_{session}` | 1 day |

Responses are cached in the `simgrid_cache` table. Every failing path falls
back to `read_stale_cache` and calls `mark_stale()`, which surfaces as an
`X-Data-Stale: true` header and a staleness banner in the UI. Admins can flush
with `DELETE /api/v1/caches/simgrid`.

---

## Admin/web URLs (not REST, Cloudflare-protected)

- `GET /admin/championships/:id/registrations.{json|csv}`
- `GET /admin/championships/:id/team_registrations.{json|csv}`

Both return `403` to server-side clients. Reachable only from a logged-in
browser.
