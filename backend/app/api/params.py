"""Path parameters: camelCase in the URL template, like everything else on the wire.

FastAPI names a path parameter after the function argument, which is
snake_case; these types carry the alias so handlers keep Python names
(``driver_id: DriverId`` for ``/drivers/{driverId}``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Path


def _uuid(name: str) -> Any:
    return Annotated[uuid.UUID, Path(alias=name)]


# SimGrid's numeric ids.
ChampionshipId = Annotated[int, Path(alias="championshipId")]
RaceId = Annotated[int, Path(alias="raceId")]

AliasId = _uuid("aliasId")
CommunityId = _uuid("communityId")
CustomChampionshipId = _uuid("championshipId")
CustomRaceId = _uuid("raceId")
DriverId = _uuid("driverId")
ImportId = _uuid("importId")
IncidentDriverId = _uuid("incidentDriverId")
IncidentId = _uuid("incidentId")
PageId = _uuid("pageId")
PointId = _uuid("pointId")
PresetId = _uuid("presetId")
RuleId = _uuid("ruleId")
UserId = _uuid("userId")
WindowId = _uuid("windowId")
