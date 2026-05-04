import { inject, Injectable } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';

const LANG_TO_LOCALE: Record<string, string> = {
  en: 'en-GB',
  uk: 'uk-UA',
};

@Injectable({ providedIn: 'root' })
export class LocaleService {
  private readonly transloco = inject(TranslocoService);

  /** Returns a JS locale string (e.g. 'en-GB', 'uk-UA') based on the active transloco language. */
  get locale(): string {
    return LANG_TO_LOCALE[this.transloco.getActiveLang()] ?? 'en-GB';
  }
}
