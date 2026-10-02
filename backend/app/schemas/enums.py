"""Closed sets of values the API speaks.

Enum classes rather than ``Literal`` so each set is one named schema in
OpenAPI (and one type on the frontend) instead of a copy per field.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    DRIVER = "driver"
    MODERATOR = "moderator"
    RACING_JUDGE = "racing_judge"
    COMMUNITY_MANAGER = "community_manager"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class Sim(StrEnum):
    """Simulators whose result files can be imported."""

    LMU = "lmu"
    IRACING = "iracing"


class RaceStatus(StrEnum):
    """``classified`` covers every non-DNS finisher when SimGrid gives no
    status (iRacing): it cannot tell a retirement from a car several laps down."""

    CLASSIFIED = "classified"
    DNF = "dnf"
    DQ = "dq"
    DNS = "dns"


class RaceSessionKind(StrEnum):
    RACE = "race"
    QUALIFYING = "qualifying"


class IncidentSource(StrEnum):
    """``filed`` by a person; ``ingested`` from a race-result file."""

    FILED = "filed"
    INGESTED = "ingested"

    @classmethod
    def _missing_(cls, value: object) -> IncidentSource:
        # Rows written before the two values were settled: whatever was not
        # filed by a person came from a machine.
        return cls.INGESTED


class IncidentStatus(StrEnum):
    """``resolved`` once every driver in the incident has a resolution."""

    OPEN = "open"
    RESOLVED = "resolved"

    @classmethod
    def _missing_(cls, value: object) -> IncidentStatus:
        # An unknown stored status must not break reading the window; the
        # status is recomputed on the next resolution anyway.
        return cls.OPEN


class CalendarEventSource(StrEnum):
    SIMGRID = "simgrid"
    CUSTOM = "custom"
