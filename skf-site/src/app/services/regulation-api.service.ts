import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { API } from '../api';

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
  isVisible: boolean;
  title: string;
}

export interface RegulationPageOut {
  id: string;
  slug: string;
  sortOrder: number;
  isVisible: boolean;
  contents: Record<string, RegulationContentOut>;
}

export interface RegulationContentUpdate {
  title: string;
  subtitle: string;
  content: string;
}

export interface RegulationPageCreate {
  slug: string;
  sortOrder: number;
  isVisible?: boolean;
  contents: Record<string, RegulationContentUpdate>;
}

export interface RegulationPageUpdate {
  slug?: string;
  sortOrder?: number;
  isVisible?: boolean;
  contents?: Record<string, RegulationContentUpdate>;
}

@Injectable({ providedIn: 'root' })
export class RegulationApiService {
  private readonly http = inject(HttpClient);

  /** Public: list pages (for nav) */
  listPages(lang: string): Observable<RegulationPageListItem[]> {
    return this.http.get<RegulationPageListItem[]>(`${API}/regulations`, { params: { lang } });
  }

  /** Public: get single page content */
  getPage(slug: string, lang: string): Observable<RegulationContentOut> {
    return this.http.get<RegulationContentOut>(`${API}/regulations/${encodeURIComponent(slug)}`, {
      params: { lang },
    });
  }

  /** Admin: list all pages with all contents */
  adminListPages(): Observable<RegulationPageOut[]> {
    return this.http.get<RegulationPageOut[]>(`${API}/regulation-pages`);
  }

  /** Admin: create page */
  createPage(data: RegulationPageCreate): Observable<RegulationPageOut> {
    return this.http.post<RegulationPageOut>(`${API}/regulation-pages`, data);
  }

  /** Admin: partial update, keyed by the page's id (its slug may change). */
  updatePage(id: string, data: RegulationPageUpdate): Observable<RegulationPageOut> {
    return this.http.patch<RegulationPageOut>(`${API}/regulation-pages/${id}`, data);
  }

  /** Admin: delete page */
  deletePage(id: string): Observable<void> {
    return this.http.delete<void>(`${API}/regulation-pages/${id}`);
  }
}
