/** What the backend's OAuth callback put in the URL fragment. */
export type CallbackOutcome = { token: string } | { error: CallbackError };

export type CallbackError = 'blocked' | 'cancelled' | 'failed';

const ERRORS: Record<string, CallbackError> = {
  blocked: 'blocked',
  access_denied: 'cancelled',
};

export function parseCallbackFragment(hash: string): CallbackOutcome {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const token = params.get('token');
  if (token) return { token };
  return { error: ERRORS[params.get('error') ?? ''] ?? 'failed' };
}
