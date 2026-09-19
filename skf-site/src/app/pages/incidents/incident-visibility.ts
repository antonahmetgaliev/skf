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

/** True when the viewer needs telling why there is no verdict to read. */
export function showsPendingNotice(incident: Incident, canJudge: boolean): boolean {
  return !showsVerdicts(incident, canJudge);
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
