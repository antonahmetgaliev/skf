import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { concat, last, Observable, of } from 'rxjs';
import { API } from '../api';

export interface Language {
  code: string;
  name: string;
  isActive: boolean;
}

/** A flat translation bundle: `{ "some.key": "value" }`. */
export type TranslationMap = Record<string, string>;

/** Largest map the backend accepts in one PATCH. */
const MAX_KEYS_PER_PATCH = 5000;

@Injectable({ providedIn: 'root' })
export class TranslationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API}/languages`;

  getLanguages(): Observable<Language[]> {
    return this.http.get<Language[]>(this.base);
  }

  addLanguage(code: string, name: string): Observable<Language> {
    return this.http.post<Language>(this.base, { code, name });
  }

  deleteLanguage(code: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${code}`);
  }

  getTranslations(lang: string): Observable<TranslationMap> {
    return this.http.get<TranslationMap>(`${this.base}/${lang}/translations`);
  }

  /** Merge *entries* into the language: new keys are added, existing ones overwritten. */
  saveTranslations(lang: string, entries: TranslationMap): Observable<void> {
    const pairs = Object.entries(entries);
    if (pairs.length === 0) return of(undefined);
    const requests: Observable<void>[] = [];
    for (let i = 0; i < pairs.length; i += MAX_KEYS_PER_PATCH) {
      const chunk = Object.fromEntries(pairs.slice(i, i + MAX_KEYS_PER_PATCH));
      requests.push(this.http.patch<void>(`${this.base}/${lang}/translations`, chunk));
    }
    return concat(...requests).pipe(last());
  }

  deleteKey(lang: string, key: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${lang}/translations/${encodeURIComponent(key)}`);
  }
}
