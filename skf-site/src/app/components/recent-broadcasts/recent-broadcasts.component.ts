import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { BtnComponent } from '../btn/btn.component';
import { CardComponent } from '../card/card.component';
import { MediaApiService, YouTubeVideo } from '../../services/media-api.service';

@Component({
  selector: 'app-recent-broadcasts',
  imports: [RouterLink, BtnComponent, CardComponent],
  templateUrl: './recent-broadcasts.component.html',
  styleUrl: './recent-broadcasts.component.scss',
})
export class RecentBroadcastsComponent {
  private readonly mediaApi = inject(MediaApiService);

  readonly streams = signal<YouTubeVideo[]>([]);

  constructor() {
    this.loadStreams();
  }

  formatDate(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }

  private async loadStreams(): Promise<void> {
    try {
      const data = await firstValueFrom(this.mediaApi.getPastStreams(4));
      this.streams.set(data);
    } catch {
      // silently fail — section just won't show
    }
  }
}
