import { EligibleDriver } from '../../../services/giveaway-api.service';

/**
 * Drawing rules for the championship giveaway.
 *
 * The backend decides *who is eligible* (it owns the imported lap data); this
 * file owns *what happens at the draw*. Both halves are pure so the rules can
 * be tested without a component or a server — the same reason
 * `incident-visibility.ts` exists.
 */

/** Eligible drivers of one class, in the order the list should read. */
export function driversInClass(drivers: EligibleDriver[], carClass: string): EligibleDriver[] {
  return drivers.filter((d) => d.carClass === carClass);
}

/** Every class present among the eligible drivers, alphabetically. */
export function classesOf(drivers: EligibleDriver[]): string[] {
  return [...new Set(drivers.map((d) => d.carClass))].filter(Boolean).sort();
}

/**
 * Pick one winner uniformly at random.
 *
 * `random` is injected so the draw can be tested deterministically; callers
 * pass nothing and get `Math.random`. Returns null for an empty pool rather
 * than inventing a winner.
 */
export function pickWinner(
  pool: EligibleDriver[],
  random: () => number = Math.random,
): EligibleDriver | null {
  if (pool.length === 0) return null;
  // `Math.random()` is [0, 1), so the index can never reach pool.length —
  // but clamp anyway so an injected generator returning 1 cannot overflow.
  const index = Math.min(Math.floor(random() * pool.length), pool.length - 1);
  return pool[index];
}

/**
 * Whether the imported data can support the requested round threshold.
 *
 * Asking for "3 of 5" when only two rounds have been imported would quietly
 * return an empty list, which reads as "nobody qualified" rather than "the
 * data isn't in yet".
 */
export function hasEnoughRounds(importedRounds: number, minRounds: number): boolean {
  return importedRounds >= minRounds;
}
