import { computed, Injectable, signal } from '@angular/core';

export type ConsentDecision = 'granted' | 'denied';

const STORAGE_KEY = 'skf.cookieConsent';

/** Stores the visitor's analytics-cookie decision. Nothing is tracked until it is 'granted'. */
@Injectable({ providedIn: 'root' })
export class CookieConsentService {
  readonly decision = signal<ConsentDecision | null>(readStoredDecision());

  /** True while the visitor has not answered the banner yet. */
  readonly undecided = computed(() => this.decision() === null);

  accept(): void {
    this.store('granted');
  }

  decline(): void {
    this.store('denied');
  }

  /** Clears the stored choice so the banner is shown again. */
  reset(): void {
    safeStorage()?.removeItem(STORAGE_KEY);
    this.decision.set(null);
  }

  private store(decision: ConsentDecision): void {
    safeStorage()?.setItem(STORAGE_KEY, decision);
    this.decision.set(decision);
  }
}

function readStoredDecision(): ConsentDecision | null {
  const stored = safeStorage()?.getItem(STORAGE_KEY);
  return stored === 'granted' || stored === 'denied' ? stored : null;
}

/** localStorage throws in some privacy modes — treat it as unavailable rather than crashing. */
function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
