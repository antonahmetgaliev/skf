import { preliminaryRounds, resultsStatusChip } from './results-status';
import { ChampionshipRace } from '../../services/simgrid-api.service';

function race(overrides: Partial<ChampionshipRace> = {}): ChampionshipRace {
  return {
    id: 1,
    displayName: 'Round 1',
    startsAt: '2026-09-12T17:00:00Z',
    track: null,
    resultsAvailable: false,
    ended: false,
    resultsStatus: null,
    ...overrides,
  };
}

describe('resultsStatusChip', () => {
  it('has no badge for a race that has not ended', () => {
    expect(resultsStatusChip(race())).toBeNull();
  });

  it('marks a preliminary race as pending', () => {
    expect(resultsStatusChip(race({ ended: true, resultsStatus: 'preliminary' }))).toEqual({
      variant: 'pending',
      label: 'championships.resultsPreliminary',
    });
  });

  it('marks a final race as completed', () => {
    expect(resultsStatusChip(race({ ended: true, resultsStatus: 'final' }))).toEqual({
      variant: 'completed',
      label: 'championships.resultsFinal',
    });
  });
});

describe('preliminaryRounds', () => {
  it('labels preliminary races by their place in the calendar', () => {
    const races = [
      race({ id: 1, resultsStatus: 'final' }),
      race({ id: 2, resultsStatus: 'preliminary' }),
      race({ id: 3, resultsStatus: 'preliminary' }),
      race({ id: 4 }),
    ];
    expect(preliminaryRounds(races)).toEqual(['R2', 'R3']);
  });

  it('is empty when every finished race is final', () => {
    expect(preliminaryRounds([race({ resultsStatus: 'final' }), race()])).toEqual([]);
  });
});
