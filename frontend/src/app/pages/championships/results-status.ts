import { StatusChip } from '../incidents/incident-visibility';
import { ChampionshipRace } from '../../services/simgrid-api.service';

/**
 * Whether a finished race's results can still change.
 *
 * The status is SimGrid's: stewards' penalties reach results only there, so a
 * race is preliminary until SimGrid stops marking its results provisional.
 */

/** The badge of a race card; null for a race that has not ended. */
export function resultsStatusChip(race: ChampionshipRace): StatusChip | null {
  switch (race.resultsStatus) {
    case 'preliminary':
      return { variant: 'pending', label: 'championships.resultsPreliminary' };
    case 'final':
      return { variant: 'completed', label: 'championships.resultsFinal' };
    default:
      return null;
  }
}

/** Round labels (`R4`) of the races whose results are preliminary, in calendar order. */
export function preliminaryRounds(races: ChampionshipRace[]): string[] {
  return races.flatMap((race, index) =>
    race.resultsStatus === 'preliminary' ? [`R${index + 1}`] : [],
  );
}
