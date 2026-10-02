/**
 * Runtime browser configuration, injected by `env.js` before the app boots.
 *
 * In production `server.js` generates `/env.js` from environment variables, so these values can be
 * changed in Railway without rebuilding. Locally, copy `public/env.js.example` to `public/env.js`.
 *
 * Everything here is served to every visitor — public values only, never secrets.
 */
export interface SkfEnv {
  /** GA4 measurement ID, e.g. 'G-XXXXXXXXXX'. Empty or missing disables analytics. */
  GA_MEASUREMENT_ID?: string;
}

declare global {
  interface Window {
    SKF_ENV?: SkfEnv;
  }
}

export function env<K extends keyof SkfEnv>(key: K): SkfEnv[K] | undefined {
  return typeof window === 'undefined' ? undefined : window.SKF_ENV?.[key];
}
