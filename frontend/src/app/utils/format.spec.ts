import { formatGap, formatLapTime } from './format';

describe('formatLapTime', () => {
  it('formats laps and long race times', () => {
    expect(formatLapTime(93485)).toBe('1:33.485');
    expect(formatLapTime(59007)).toBe('0:59.007');
    expect(formatLapTime(4238798)).toBe('1:10:38.798');
  });

  it('falls back for missing times', () => {
    expect(formatLapTime(null)).toBe('-');
    expect(formatLapTime(0)).toBe('-');
  });
});

describe('formatGap', () => {
  it('shows seconds under a minute and m:ss above', () => {
    expect(formatGap(220)).toBe('+0.220');
    expect(formatGap(65310)).toBe('+1:05.310');
  });

  it('falls back when there is no gap', () => {
    expect(formatGap(null)).toBe('-');
  });
});
