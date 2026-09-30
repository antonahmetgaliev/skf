import { Incident, IncidentWindowOut } from '../../services/incidents-api.service';

/** Pure summaries of a round's incidents: grouping, publish preview, Discord text. */

/** A penalty about to be written to a licence by publishing. */
export interface PendingPenalty {
  driverName: string;
  session: string;
  verdict: string;
  bwpPoints: number;
  linked: boolean;
  incidentDriverId: string;
}

export interface SessionIncidents {
  session: string;
  autoItems: Incident[];
  filedItems: Incident[];
}

export interface PublishPreview {
  penalties: PendingPenalty[];
  /** BWP that will actually reach a licence (linked drivers only). */
  bwpTotal: number;
  verdictCount: number;
  noPenaltyCount: number;
}

const byTime = (a: Incident, b: Incident) => {
  if (!a.time && !b.time) return 0;
  if (!a.time) return 1;
  if (!b.time) return -1;
  return a.time.localeCompare(b.time);
};

const byLapCorner = (a: Incident, b: Incident) => {
  const lapA = parseInt(a.lap ?? '', 10);
  const lapB = parseInt(b.lap ?? '', 10);
  if (!isNaN(lapA) && !isNaN(lapB) && lapA !== lapB) return lapA - lapB;
  return (a.corner ?? '').localeCompare(b.corner ?? '');
};

const sessionOrder = (name: string): number => {
  const upper = name.toUpperCase();
  const heatMatch = upper.match(/^HEAT\s*(\d+)$/);
  if (heatMatch) return parseInt(heatMatch[1], 10);
  if (upper.startsWith('FEATURE')) return 1000;
  return 2000;
};

/**
 * Incidents by session: heats in number order, then Feature, then the rest.
 * Within a session, auto incidents by time, filed ones by lap and corner.
 */
export function groupBySession(incidents: Incident[]): SessionIncidents[] {
  const groups = new Map<string, Incident[]>();
  for (const inc of incidents) {
    const key = inc.sessionName ?? '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(inc);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => sessionOrder(a) - sessionOrder(b))
    .map(([session, items]) => ({
      session,
      autoItems: items.filter((i) => i.source !== 'filed').sort(byTime),
      filedItems: items.filter((i) => i.source === 'filed').sort(byLapCorner),
    }));
}

export function unresolvedCount(w: IncidentWindowOut): number {
  return w.incidents.filter((inc) => inc.status !== 'resolved').length;
}

/** Every penalty that publishing would irreversibly write to a licence. */
export function pendingPenalties(w: IncidentWindowOut): PendingPenalty[] {
  const rows: PendingPenalty[] = [];
  for (const inc of w.incidents) {
    for (const drv of inc.drivers) {
      const res = drv.resolution;
      if (!res || !res.bwpPoints || res.bwpApplied) continue;
      rows.push({
        driverName: drv.driverName,
        session: inc.sessionName ?? '',
        verdict: res.verdict,
        bwpPoints: res.bwpPoints,
        linked: drv.driverId !== null,
        incidentDriverId: drv.id,
      });
    }
  }
  return rows;
}

export function publishPreview(w: IncidentWindowOut): PublishPreview {
  const penalties = pendingPenalties(w);
  const drivers = w.incidents.flatMap((i) => i.drivers);
  return {
    penalties,
    bwpTotal: penalties.filter((p) => p.linked).reduce((sum, p) => sum + p.bwpPoints, 0),
    verdictCount: drivers.filter((d) => d.resolution).length,
    // Verdicts going public that carry no penalty — named, not listed.
    noPenaltyCount: drivers.filter((d) => d.resolution && !d.resolution.bwpPoints).length,
  };
}

/** One line per verdict, ready to paste into the Discord decisions channel. */
export function discordDecisionsText(w: IncidentWindowOut): string {
  const lines: string[] = [w.raceName];
  for (const inc of w.incidents) {
    for (const drv of inc.drivers) {
      if (!drv.resolution) continue;
      const parts: string[] = [];
      if (inc.sessionName) parts.push(inc.sessionName);
      if (inc.time) parts.push(inc.time);
      if (inc.lap) parts.push(`Lap ${inc.lap}`);
      if (inc.corner) parts.push(inc.corner);
      parts.push(drv.driverName);
      const desc = drv.resolution.description ?? '';
      if (desc) parts.push(desc);
      parts.push(drv.resolution.verdict);
      parts.push(drv.resolution.bwpPoints ? `${drv.resolution.bwpPoints} BWP` : '-');
      lines.push(parts.join(' | '));
    }
  }
  return lines.join('\n\n');
}
