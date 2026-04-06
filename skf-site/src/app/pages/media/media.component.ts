import { Component, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { MediaApiService, YouTubeVideo } from '../../services/media-api.service';

const PAGE_SIZE = 12;

@Component({
  selector: 'app-media',
  imports: [PageIntroComponent, PageLayoutComponent, CardComponent, BtnComponent],
  templateUrl: './media.component.html',
  styleUrl: './media.component.scss',
})
export class MediaComponent {
  private readonly mediaApi = inject(MediaApiService);

  readonly allPastVideos = signal<YouTubeVideo[]>([]);
  readonly allUpcomingVideos = signal<YouTubeVideo[]>([]);
  readonly loading = signal(false);
  readonly errorMessage = signal('');

  readonly pastVisible = signal(PAGE_SIZE);
  readonly upcomingVisible = signal(PAGE_SIZE);

  readonly pastVideos = computed(() => this.allPastVideos().slice(0, this.pastVisible()));
  readonly upcomingVideos = computed(() => this.allUpcomingVideos().slice(0, this.upcomingVisible()));
  readonly hasMorePast = computed(() => this.pastVisible() < this.allPastVideos().length);
  readonly hasMoreUpcoming = computed(() => this.upcomingVisible() < this.allUpcomingVideos().length);

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

  showMorePast(): void {
    this.pastVisible.update(v => v + PAGE_SIZE);
  }

  showMoreUpcoming(): void {
    this.upcomingVisible.update(v => v + PAGE_SIZE);
  }

  private async loadVideos(): Promise<void> {
    this.loading.set(true);
    try {
      const [past, upcoming] = await Promise.all([
        firstValueFrom(this.mediaApi.getLiveStreams(200)),
        firstValueFrom(this.mediaApi.getUpcomingStreams(50)),
      ]);
      this.allPastVideos.set(past);
      this.allUpcomingVideos.set(upcoming);
    } catch {
      this.errorMessage.set('Failed to load videos.');
    } finally {
      this.loading.set(false);
    }
  }
}
