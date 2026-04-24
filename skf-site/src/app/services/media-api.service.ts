import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable, shareReplay } from 'rxjs';
import { toLocalDateStr } from '../utils/date';

export interface YouTubeVideo {
  videoId: string;
  title: string;
  description: string;
  publishedAt: string;
  thumbnailUrl: string;
}

@Injectable({ providedIn: 'root' })
export class MediaApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/youtube';

  private pastCache$: Observable<YouTubeVideo[]> | null = null;
  private pastCacheLimit = 0;

  private upcomingCache$: Observable<YouTubeVideo[]> | null = null;
  private upcomingCacheLimit = 0;

  getPastStreams(limit = 10): Observable<YouTubeVideo[]> {
    if (!this.pastCache$ || limit > this.pastCacheLimit) {
      this.pastCacheLimit = limit;
      this.pastCache$ = this.http
        .get<YouTubeVideo[]>(`${this.base}/past-streams`, {
          params: { limit: String(limit) },
        })
        .pipe(shareReplay(1));
    }
    return this.pastCache$.pipe(map((items) => items.slice(0, limit)));
  }

  getUpcomingStreams(limit = 10): Observable<YouTubeVideo[]> {
    if (!this.upcomingCache$ || limit > this.upcomingCacheLimit) {
      this.upcomingCacheLimit = limit;
      this.upcomingCache$ = this.http
        .get<YouTubeVideo[]>(`${this.base}/upcoming-streams`, {
          params: { limit: String(limit) },
        })
        .pipe(shareReplay(1));
    }
    return this.upcomingCache$.pipe(map((items) => items.slice(0, limit)));
  }

  getTodayBroadcasts(): Observable<YouTubeVideo[]> {
    const todayStr = toLocalDateStr(new Date().toISOString());

    return new Observable<YouTubeVideo[]>((subscriber) => {
      Promise.all([
        this.toPromise(this.getPastStreams(10)),
        this.toPromise(this.getUpcomingStreams(50)),
      ])
        .then(([past, upcoming]) => {
          const seen = new Set<string>();
          const result: YouTubeVideo[] = [];

          // Upcoming/live first, then completed — deduplicate by videoId
          for (const s of [...upcoming, ...past]) {
            if (toLocalDateStr(s.publishedAt) === todayStr && !seen.has(s.videoId)) {
              seen.add(s.videoId);
              result.push(s);
            }
          }

          subscriber.next(result);
          subscriber.complete();
        })
        .catch((err) => subscriber.error(err));
    });
  }

  private toPromise<T>(obs: Observable<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      obs.subscribe({ next: resolve, error: reject });
    });
  }
}
