import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface RegulationContentOut {
  lang: string;
  title: string;
  subtitle: string;
  content: string;
}

export interface RegulationPageListItem {
  id: string;
  slug: string;
  sortOrder: number;
  title: string;
}

export interface RegulationPageOut {
  id: string;
  slug: string;
  sortOrder: number;
  contents: Record<string, RegulationContentOut>;
}

export interface RegulationContentUpdate {
  title: string;
  subtitle: string;
  content: string;
}

export interface RegulationPageCreate {
  slug: string;
  sort_order: number;
  contents: Record<string, RegulationContentUpdate>;
}

export interface RegulationPageUpdate {
  slug?: string;
  sort_order?: number;
  contents?: Record<string, RegulationContentUpdate>;
}

@Injectable({ providedIn: 'root' })
export class RegulationApiService {
  private readonly http = inject(HttpClient);

  /** Public: list pages (for nav) */
  listPages(lang: string): Observable<RegulationPageListItem[]> {
    return this.http.get<RegulationPageListItem[]>(`/api/regulations?lang=${lang}`);
  }

  /** Public: get single page content */
  getPage(slug: string, lang: string): Observable<RegulationContentOut> {
    return this.http.get<RegulationContentOut>(`/api/regulations/${slug}?lang=${lang}`);
  }

  /** Admin: list all pages with all contents */
  adminListPages(): Observable<RegulationPageOut[]> {
    return this.http.get<RegulationPageOut[]>('/api/admin/regulations');
  }

  /** Admin: create page */
  createPage(data: RegulationPageCreate): Observable<RegulationPageOut> {
    return this.http.post<RegulationPageOut>('/api/admin/regulations', data);
  }

  /** Admin: update page */
  updatePage(slug: string, data: RegulationPageUpdate): Observable<RegulationPageOut> {
    return this.http.put<RegulationPageOut>(`/api/admin/regulations/${slug}`, data);
  }

  /** Admin: delete page */
  deletePage(slug: string): Observable<void> {
    return this.http.delete<void>(`/api/admin/regulations/${slug}`);
  }
}
