import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

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

  getLiveStreams(limit = 10): Observable<YouTubeVideo[]> {
    return this.http.get<YouTubeVideo[]>(`${this.base}/live-streams`, {
      params: { limit: String(limit) },
    });
  }

  getUpcomingStreams(limit = 10): Observable<YouTubeVideo[]> {
    return this.http.get<YouTubeVideo[]>(`${this.base}/upcoming-streams`, {
      params: { limit: String(limit) },
    });
  }
}
