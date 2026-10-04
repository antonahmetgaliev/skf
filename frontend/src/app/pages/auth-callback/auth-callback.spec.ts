import { parseCallbackFragment } from './auth-callback';

describe('parseCallbackFragment', () => {
  it('reads the refresh token', () => {
    expect(parseCallbackFragment('#token=abc-_123')).toEqual({ token: 'abc-_123' });
  });

  it('tells a blocked account and a declined consent apart from other failures', () => {
    expect(parseCallbackFragment('#error=blocked')).toEqual({ error: 'blocked' });
    expect(parseCallbackFragment('#error=access_denied')).toEqual({ error: 'cancelled' });
    expect(parseCallbackFragment('#error=upstream_error')).toEqual({ error: 'failed' });
    expect(parseCallbackFragment('#error=invalid_state')).toEqual({ error: 'failed' });
  });

  it('treats an empty or foreign fragment as a failure', () => {
    expect(parseCallbackFragment('')).toEqual({ error: 'failed' });
    expect(parseCallbackFragment('#section')).toEqual({ error: 'failed' });
  });
});
