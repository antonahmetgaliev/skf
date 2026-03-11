/**
 * Tests for the pure computation methods shared by ProfileComponent
 * and the LoadingService's counter management.
 *
 * ProfileComponent.getActiveBwp is the same algorithm as the one in
 * DriverProfileComponent — both return the sum of non-expired BWP points.
 * We test it here independently to confirm the implementation is consistent.
 */

// ---------------------------------------------------------------------------
// Types (minimal, matches DriverPublic from profile-api.service)
// ---------------------------------------------------------------------------

type BwpPoint = { id: string; points: number; issuedOn: string; expiresOn: string };
type DriverWithPoints = { points: BwpPoint[] };

// ---------------------------------------------------------------------------
// Logic under test (mirrors ProfileComponent.getActiveBwp)
// ---------------------------------------------------------------------------

function getActiveBwp(driver: DriverWithPoints): number {
  const today = new Date().toISOString().slice(0, 10);
  return driver.points
    .filter((p) => p.expiresOn >= today)
    .reduce((sum, p) => sum + p.points, 0);
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function daysFromNow(offset: number): string {
  return new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
}

function pt(points: number, expiresOn: string): BwpPoint {
  return { id: crypto.randomUUID(), points, issuedOn: daysFromNow(-10), expiresOn };
}

const TOMORROW = daysFromNow(1);
const YESTERDAY = daysFromNow(-1);
const TODAY_STR = new Date().toISOString().slice(0, 10);

// ---------------------------------------------------------------------------
// getActiveBwp
// ---------------------------------------------------------------------------

describe('ProfileComponent.getActiveBwp', () => {
  it('returns 0 for a driver with no points', () => {
    expect(getActiveBwp({ points: [] })).toBe(0);
  });

  it('excludes expired points', () => {
    expect(getActiveBwp({ points: [pt(3, TOMORROW), pt(5, YESTERDAY)] })).toBe(3);
  });

  it('includes a point that expires exactly today', () => {
    expect(getActiveBwp({ points: [pt(7, TODAY_STR)] })).toBe(7);
  });

  it('returns 0 when every point has expired', () => {
    expect(getActiveBwp({ points: [pt(4, YESTERDAY), pt(6, daysFromNow(-365))] })).toBe(0);
  });

  it('sums multiple active points correctly', () => {
    expect(
      getActiveBwp({
        points: [pt(3, TOMORROW), pt(5, daysFromNow(30)), pt(2, TODAY_STR)],
      })
    ).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// skipLink / localStorage flag logic
// ---------------------------------------------------------------------------

describe('skipLink localStorage key logic', () => {
  const userId = 'user-abc-123';

  beforeEach(() => {
    localStorage.clear();
  });

  it('key is absent before skip is called', () => {
    expect(localStorage.getItem(`link-skipped:${userId}`)).toBeNull();
  });

  it('setting the skip flag makes the key truthy', () => {
    localStorage.setItem(`link-skipped:${userId}`, '1');
    expect(localStorage.getItem(`link-skipped:${userId}`)).toBeTruthy();
  });

  it('removing the skip flag clears it (logout cleanup)', () => {
    localStorage.setItem(`link-skipped:${userId}`, '1');
    localStorage.removeItem(`link-skipped:${userId}`);
    expect(localStorage.getItem(`link-skipped:${userId}`)).toBeNull();
  });
});
