import { BadgeVariant } from '../../components/badge/badge.component';
import { Incident, IncidentDriver } from '../../services/incidents-api.service';

/**
 * What each role is allowed to learn about an incident.
 *
 * The server withholds `resolution` from non-judges until the window is
 * published, which leaves "not judged yet" and "judged but withheld" looking
 * identical in the payload. Deciding that here, rather than in template
 * conditions, keeps the two readings of the same data in one place — and makes
 * the policy testable without compiling a component.
 */

export interface StatusChip {
  variant: BadgeVariant;
  label: string;
}

/** True when the viewer may see verdicts on this incident at all. */
export function showsVerdicts(incident: Incident, canJudge: boolean): boolean {
  return canJudge || incident.isPublished;
}

/**
 * The status as the viewer should understand it.
 *
 * A driver is told where *they* stand, not how far the stewards have got: until
 * the round is published the answer is "under review" whether or not a verdict
 * already exists. Revealing that one exists would leak the stewards' progress,
 * and they may still revise it before publishing.
 */
export function incidentStatusChip(incident: Incident, canJudge: boolean): StatusChip {
  if (!showsVerdicts(incident, canJudge)) {
    return { variant: 'pending', label: 'incidents.underReview' };
  }
  return incident.status === 'resolved'
    ? { variant: 'resolved', label: 'incidents.resolved' }
    : { variant: 'pending', label: 'incidents.statusOpen' };
}

/**
 * True for the row-level chrome that only means something to a steward: the
 * per-driver status badge and the unlinked-driver flag. Shown to a driver, the
 * badge either contradicts the card or repeats the verdict printed beside it,
 * and the unlinked flag is internal plumbing about name matching.
 */
export function showsStewardDetail(canJudge: boolean): boolean {
  return canJudge;
}

/** One named penalty on the collapsed tile. */
export interface IncidentPenalty {
  driverName: string;
  verdict: string;
}

/**
 * The penalties worth naming on the collapsed tile, or [] when there is
 * nothing to say.
 *
 * Only non-default verdicts appear: "everyone got NFA" is noise, and the
 * verdict text alone cannot distinguish a judge who chose the default from one
 * who never touched the row — both store the same string. Withheld rounds
 * return [] regardless: the tile must not leak what the card body refuses to
 * show.
 */
export function incidentPenalties(
  incident: Incident,
  defaultVerdict: string | undefined,
  canJudge: boolean,
): IncidentPenalty[] {
  if (!showsVerdicts(incident, canJudge)) return [];

  const judged = incident.drivers.filter((d) => d.resolution);
  const named = (drivers: IncidentDriver[]): IncidentPenalty[] =>
    drivers.map((d) => ({ driverName: d.driverName, verdict: d.resolution!.verdict }));

  if (defaultVerdict !== undefined) {
    return named(judged.filter((d) => d.resolution!.verdict !== defaultVerdict));
  }

  // No default to compare against — the rules failed to load, or the league
  // deleted the rule that was flagged default. One verdict shared by everyone
  // is a collective outcome and says nothing a tile needs; a split decision
  // still gets named in full rather than silently swallowed.
  const distinct = new Set(judged.map((d) => d.resolution!.verdict));
  return distinct.size <= 1 ? [] : named(judged);
}

/**
 * The one decision reason shared by every judged driver, or null when the rows
 * disagree.
 *
 * A reason is authored once per incident and fanned out onto each driver's
 * resolution by the server, so printing it per row repeats the same sentence N
 * times. Divergence is unreachable through the judge UI but the column allows
 * it, and null lets the caller fall back to per-row rendering.
 */
export function sharedDecisionDescription(incident: Incident): string | null {
  const descriptions = new Set(
    incident.drivers
      .map((d) => d.resolution?.description)
      .filter((text): text is string => !!text),
  );
  return descriptions.size === 1 ? [...descriptions][0] : null;
}

/**
 * The badge for one driver's row, or null when it would only repeat what the
 * row already shows.
 *
 * The row carries the selected verdict chip and, when it matters, the BWP
 * field; the card header carries the incident's own status. So a per-driver
 * "Resolved" is said three times over and earns nothing. What the row cannot
 * otherwise show is where the penalty *went*: decided but not yet on the
 * licence, or issued. Those get a badge; the rest do not.
 */
export function driverStatusBadge(
  driver: IncidentDriver,
  incident: Incident,
): StatusChip | null {
  // Deliberately blind to the verdict text: a league may rename or delete any
  // rule, so behaviour keys off BWP, which is what actually has consequences.
  if (!driver.resolution) {
    // Only worth flagging when it contradicts the header — an incident counted
    // as resolved that still holds a driver nobody has judged.
    return incident.status === 'resolved'
      ? { variant: 'pending', label: 'incidents.statusOpen' }
      : null;
  }
  if (driver.resolution.bwpApplied) {
    return { variant: 'applied', label: 'incidents.bwpApplied' };
  }
  if (driver.resolution.bwpPoints) {
    return { variant: 'bwp-pending', label: 'incidents.bwpPending' };
  }
  return null;
}
