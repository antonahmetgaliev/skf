# Features

Pages live in `frontend/src/app/pages/`, frontend services in `frontend/src/app/services/`, backend routers in `backend/app/api/v1/`, backend services in `backend/app/services/`, models in `backend/app/models/`. For endpoints, see `/docs` on the backend.

| Feature | Page | Frontend service | Router | Backend service | Models |
|---|---|---|---|---|---|
| Login and account | `profile/`, `auth-callback/` | `auth.service`, `auth-tokens.service`, `profile-api.service` | `auth`, `me` | `auth`, `tokens`, `discord` | `user` (User, Role, RefreshToken) |
| Users and roles (admin) | `admin/` (`user-item`) | `auth.service` | `users` | `users` | `user`, `community_manager` |
| Drivers and BWP licence points | `bwp-license/`, `drivers-list/`, `driver-profile/` | `bwp-api.service` | `drivers`, `penalty_rules`, `driver_aliases` | `drivers`, `bwp`, `driver_matching` | `bwp` (Driver, BwpPoint, PenaltyRule, PenaltyClearance) |
| Championships and standings | `championships/`, `home-visit/` | `simgrid-api.service`, `championship.service` | `championships`, `sim_catalog` | `championships`, `championship_results`, `simgrid`, `cache` | `simgrid_cache`, `active_championship` |
| Race-result uploads and giveaway | `admin/` (race-results and giveaway tabs) | `race-results-api.service`, `giveaway-api.service` | `race_result_imports`, `championships` (giveaway) | `race_import`, `race_incidents`, `race_files/`, `file_storage`, `giveaway` | `race_result` |
| Incidents and judging | `incidents/` | `incidents-api.service` | `incident_windows`, `incidents`, `verdict_rules` | `incidents`, `incident_rules`, `incident_bwp`, `incident_audit` | `incidents` |
| Calendar and communities | `calendar/`, `admin/` (calendar tab) | `calendar-api.service` | `calendar_events`, `communities`, `custom_championships` | `calendar_events`, `communities`, `custom_championships` | `community` (Community, Game), `custom_championship` |
| Regulations | `regulations/` | `regulation-api.service` | `regulations` | `regulations` | `regulation` |
| Translations | `admin/` (translations tab) | `translation-api.service` | `languages` | `translations` | `translation` |
| Media (YouTube) | `media/` | `media-api.service` | `youtube` | `youtube`, `cache` | `simgrid_cache` (shared cache table) |
| Club history | `skf-history/` | — | — | — | — (static page) |

## How features affect each other
- **Incident → BWP.** Publishing an incident window (`incidents.publish_window`) turns each driver's verdict into BWP points through `incident_bwp.apply_resolution_bwp`. Drivers whose name matched no `Driver` at publish time get their point later from the BWP backfill (admin). BWP is therefore mostly a *result* of judging, not a separate input.
- **Race-result upload → incidents and giveaway.** One uploaded file per SimGrid round (`race_import`) stores the classification that `giveaway` uses to check eligibility. It can also open the round's incident window and add Auto incidents (`race_incidents`).
- **Name matching is shared.** Incidents, BWP and race uploads all map free-text driver names to `Driver` rows via `driver_matching.match_driver_id_by_name`. The giveaway also applies admin-defined aliases. A bad match shows up in all of these features.
- **SimGrid behind everything championship-related.** Championships, standings, the calendar's SimGrid events and upload rounds all come from `simgrid.simgrid_service`, cached in `simgrid_cache`. When SimGrid is down, pages keep working on stale data (`X-Data-Stale`).
- **Calendar = SimGrid + custom.** `calendar_events` merges SimGrid championships with custom championships created by community managers. Access is scoped per community (`community_manager`).
- **Roles gate the UI and the API.** `auth.service` on the frontend mirrors the backend roles. The "view as" switch in the header only changes what the UI shows; the API still checks the real role.
