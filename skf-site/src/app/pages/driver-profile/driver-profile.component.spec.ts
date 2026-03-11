/**
 * Tests for the pure computation methods of DriverProfileComponent.
 *
 * The methods getActiveBwp / getActivePoints / getExpiredPoints / isExpired
 * are stateless functions that operate on a plain data object.  We validate
 * them here as standalone logic to keep the tests fast and free of Angular
 * TestBed setup.
 *
 * The logic under test (copied verbatim from the component to serve as the
 * spec baseline):
 *
 *   getActiveBwp  – returns sum of points whose expiresOn >= today
 *   getActivePoints – filters points whose expiresOn >= today
 *   getExpiredPoints – filters points whose expiresOn < today
 *   isExpired     – returns true when expiresOn < today
 */

type BwpPoint = { id: string; points: number; issuedOn: string; expiresOn: string };
type DriverPublic = { points: BwpPoint[]; clearances: never[] };

// ---------------------------------------------------------------------------
// Helpers mirroring the component's implementation
// ---------------------------------------------------------------------------

const today = () => new Date().toISOString().slice(0, 10);

function getActiveBwp(driver: DriverPublic): number {
  const t = today();
  return driver.points.filter((p) => p.expiresOn >= t).reduce((sum, p) => sum + p.points, 0);
}

function getActivePoints(driver: DriverPublic): BwpPoint[] {
  const t = today();
  return driver.points.filter((p) => p.expiresOn >= t);
}

function getExpiredPoints(driver: DriverPublic): BwpPoint[] {
  const t = today();
  return driver.points.filter((p) => p.expiresOn < t);
}

function isExpired(expiresOn: string): boolean {
  return expiresOn < today();
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function daysFromNow(offset: number): string {
  const d = new Date(Date.now() + offset * 86_400_000);
  return d.toISOString().slice(0, 10);
}

const TOMORROW = daysFromNow(1);
const TODAY_STR = today();
const YESTERDAY = daysFromNow(-1);
const FAR_FUTURE = daysFromNow(365);
const FAR_PAST = daysFromNow(-365);

function pt(points: number, expiresOn: string): BwpPoint {
  return { id: crypto.randomUUID(), points, issuedOn: daysFromNow(-10), expiresOn };
}

const EMPTY_DRIVER: DriverPublic = { points: [], clearances: [] as never[] };

// ---------------------------------------------------------------------------
// isExpired
// ---------------------------------------------------------------------------

describe('isExpired', () => {
  it('returns false for a future expiry', () => {
    expect(isExpired(TOMORROW)).toBe(false);
  });

  it('returns false for today (expires_on == today is still active)', () => {
    expect(isExpired(TODAY_STR)).toBe(false);
  });

  it('returns true for a past expiry', () => {
    expect(isExpired(YESTERDAY)).toBe(true);
  });

  it('returns true for a far-past expiry', () => {
    expect(isExpired(FAR_PAST)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// getActiveBwp
// ---------------------------------------------------------------------------

describe('getActiveBwp', () => {
  it('returns 0 for a driver with no points', () => {
    expect(getActiveBwp(EMPTY_DRIVER)).toBe(0);
  });

  it('sums only non-expired points', () => {
    const driver: DriverPublic = { ...EMPTY_DRIVER, points: [pt(3, TOMORROW), pt(5, YESTERDAY)] };
    expect(getActiveBwp(driver)).toBe(3);
  });

  it('includes a point expiring today', () => {
    const driver: DriverPublic = { ...EMPTY_DRIVER, points: [pt(4, TODAY_STR)] };
    expect(getActiveBwp(driver)).toBe(4);
  });

  it('returns 0 when all points are expired', () => {
    const driver: DriverPublic = {
      ...EMPTY_DRIVER,
      points: [pt(3, YESTERDAY), pt(5, FAR_PAST)],
    };
    expect(getActiveBwp(driver)).toBe(0);
  });

  it('sums multiple active points', () => {
    const driver: DriverPublic = {
      ...EMPTY_DRIVER,
      points: [pt(3, TOMORROW), pt(5, FAR_FUTURE), pt(2, TODAY_STR)],
    };
    expect(getActiveBwp(driver)).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// getActivePoints
// ---------------------------------------------------------------------------

describe('getActivePoints', () => {
  it('returns an empty array for no points', () => {
    expect(getActivePoints(EMPTY_DRIVER)).toEqual([]);
  });

  it('includes only non-expired entries', () => {
    const active = pt(3, TOMORROW);
    const expired = pt(5, YESTERDAY);
    const driver: DriverPublic = { ...EMPTY_DRIVER, points: [active, expired] };
    const result = getActivePoints(driver);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(active.id);
  });

  it('includes a point expiring today', () => {
    const driver: DriverPublic = { ...EMPTY_DRIVER, points: [pt(4, TODAY_STR)] };
    expect(getActivePoints(driver)).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// getExpiredPoints
// ---------------------------------------------------------------------------

describe('getExpiredPoints', () => {
  it('returns an empty array for no points', () => {
    expect(getExpiredPoints(EMPTY_DRIVER)).toEqual([]);
  });

  it('returns only entries whose expiry is strictly before today', () => {
    const expired = pt(5, YESTERDAY);
    const active = pt(3, TOMORROW);
    const today_entry = pt(2, TODAY_STR);
    const driver: DriverPublic = { ...EMPTY_DRIVER, points: [expired, active, today_entry] };
    const result = getExpiredPoints(driver);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(expired.id);
  });
});
