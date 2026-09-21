import { describe, expect, it } from 'vitest';
import { EligibleDriver } from '../../../services/giveaway-api.service';
import { classesOf, driversInClass, hasEnoughRounds, pickWinner } from './giveaway-eligibility';

function driver(displayName: string, carClass: string, qualifyingRounds = 3): EligibleDriver {
  return { identity: displayName.toLowerCase(), displayName, carClass, qualifyingRounds, rounds: [] };
}

const POOL = [driver('Max Tarasenko', 'Hyper'), driver('Bohdan Tseliuk', 'GT3'), driver('Roma Fedin', 'GT3')];

describe('classesOf', () => {
  it('lists each class once, alphabetically', () => {
    expect(classesOf(POOL)).toEqual(['GT3', 'Hyper']);
  });

  it('ignores blank classes rather than showing an unnamed group', () => {
    expect(classesOf([...POOL, driver('Unknown', '')])).toEqual(['GT3', 'Hyper']);
  });

  it('returns nothing for an empty pool', () => {
    expect(classesOf([])).toEqual([]);
  });
});

describe('driversInClass', () => {
  it('keeps the classes separate, as the regulation draws them', () => {
    expect(driversInClass(POOL, 'GT3').map((d) => d.displayName)).toEqual([
      'Bohdan Tseliuk',
      'Roma Fedin',
    ]);
    expect(driversInClass(POOL, 'Hyper').map((d) => d.displayName)).toEqual(['Max Tarasenko']);
  });
});

describe('pickWinner', () => {
  it('selects by index across the whole pool', () => {
    expect(pickWinner(POOL, () => 0)?.displayName).toBe('Max Tarasenko');
    expect(pickWinner(POOL, () => 0.5)?.displayName).toBe('Bohdan Tseliuk');
    expect(pickWinner(POOL, () => 0.999)?.displayName).toBe('Roma Fedin');
  });

  it('cannot overflow when the generator returns 1', () => {
    expect(pickWinner(POOL, () => 1)?.displayName).toBe('Roma Fedin');
  });

  it('returns null instead of inventing a winner for an empty pool', () => {
    expect(pickWinner([], () => 0)).toBeNull();
  });

  it('gives every driver a chance over many draws', () => {
    const seen = new Set<string>();
    for (let i = 0; i < 300; i++) seen.add(pickWinner(POOL)!.displayName);
    expect(seen.size).toBe(POOL.length);
  });
});

describe('hasEnoughRounds', () => {
  it('flags a threshold the imported data cannot satisfy', () => {
    expect(hasEnoughRounds(2, 3)).toBe(false);
    expect(hasEnoughRounds(3, 3)).toBe(true);
    expect(hasEnoughRounds(5, 3)).toBe(true);
  });
});
