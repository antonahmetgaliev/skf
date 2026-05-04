import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface Language {
  code: string;
  name: string;
  is_active: boolean;
}

export interface TranslationItem {
  key: string;
  value: string;
}

@Injectable({ providedIn: 'root' })
export class TranslationApiService {
  private readonly http = inject(HttpClient);

  getLanguages(): Observable<Language[]> {
    return this.http.get<Language[]>('/api/admin/languages');
  }

  addLanguage(code: string, name: string): Observable<Language> {
    return this.http.post<Language>('/api/admin/languages', { code, name });
  }

  deleteLanguage(code: string): Observable<void> {
    return this.http.delete<void>(`/api/admin/languages/${code}`);
  }

  getTranslations(lang: string): Observable<TranslationItem[]> {
    return this.http.get<TranslationItem[]>('/api/admin/translations', { params: { lang } });
  }

  saveTranslations(lang: string, items: TranslationItem[]): Observable<void> {
    return this.http.put<void>(`/api/admin/translations/${lang}`, { items });
  }

  deleteKey(lang: string, key: string): Observable<void> {
    return this.http.delete<void>(`/api/admin/translations/${lang}/${key}`);
  }

  exportTranslations(lang: string): Observable<Record<string, string>> {
    return this.http.get<Record<string, string>>(`/api/admin/translations/export/${lang}`);
  }

  importTranslations(lang: string, file: File): Observable<void> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<void>(`/api/admin/translations/import/${lang}`, formData);
  }
}
