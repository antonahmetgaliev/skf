import { Component, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { MediaApiService, YouTubeVideo } from '../../services/media-api.service';

@Component({
  selector: 'app-media',
  imports: [PageIntroComponent, PageLayoutComponent, CardComponent],
  templateUrl: './media.component.html',
  styleUrl: './media.component.scss',
})
export class MediaComponent {
  private readonly mediaApi = inject(MediaApiService);

  readonly videos = signal<YouTubeVideo[]>([]);
  readonly loading = signal(false);
  readonly errorMessage = signal('');

  constructor() {
    this.loadVideos();
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

  private async loadVideos(): Promise<void> {
    this.loading.set(true);
    try {
      const data = await firstValueFrom(this.mediaApi.getLiveStreams(50));
      this.videos.set(data);
    } catch {
      this.errorMessage.set('Failed to load videos.');
    } finally {
      this.loading.set(false);
    }
  }
}
