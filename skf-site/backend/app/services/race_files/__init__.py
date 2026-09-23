"""Race result files from each supported simulator.

One uploaded file per championship round feeds both the giveaway (laps per
driver) and the stewards' "Auto" incidents (multi-car contacts). The
simulator is never guessed from the file: it follows from the SimGrid
championship's game, so a wrong file type is refused rather than misread.
"""

from __future__ import annotations

from app.services.race_files import iracing, lmu
from app.services.race_files.types import (
    MAX_UPLOAD_BYTES,
    ParsedContact,
    ParsedEntry,
    ParsedRaceFile,
    RaceFileError,
    Sim,
)

__all__ = [
    "MAX_UPLOAD_BYTES",
    "ParsedContact",
    "ParsedEntry",
    "ParsedRaceFile",
    "RaceFileError",
    "Sim",
    "FILE_EXTENSIONS",
    "parse_race_file",
    "sim_for_game",
]

# SimGrid game name -> simulator whose result file we can parse.
_GAMES: dict[str, Sim] = {
    "le mans ultimate": "lmu",
    "iracing": "iracing",
}

FILE_EXTENSIONS: dict[Sim, str] = {"lmu": "xml", "iracing": "bin"}


def sim_for_game(game_name: str | None) -> Sim | None:
    """The simulator for a SimGrid game name, or None when unsupported."""
    return _GAMES.get((game_name or "").strip().lower())


def parse_race_file(payload: bytes, sim: Sim) -> ParsedRaceFile:
    if not payload:
        raise RaceFileError("File is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise RaceFileError("File is too large")
    if sim == "lmu":
        return lmu.parse(payload)
    if sim == "iracing":
        return iracing.parse(payload)
    raise RaceFileError(f"Unsupported simulator: {sim}")
