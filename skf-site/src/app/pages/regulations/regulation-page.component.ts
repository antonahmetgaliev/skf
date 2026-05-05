import { Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { TranslocoService } from '@jsverse/transloco';
import { Subscription } from 'rxjs';
import { CardComponent } from '../../components/card/card.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { MarkdownPipe } from '../../pipes/markdown.pipe';
import { RegulationApiService, RegulationContentOut } from '../../services/regulation-api.service';

@Component({
  selector: 'app-regulation-page',
  imports: [CardComponent, EmptyComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, MarkdownPipe],
  template: `
    <app-page>
      @if (loading()) {
        <app-spinner />
      } @else if (content(); as c) {
        <app-page-intro [title]="c.title" [subtitle]="c.subtitle" />
        <app-card [animated]="true">
          <div class="regulation-content" [innerHTML]="c.content | markdown"></div>
        </app-card>
      } @else {
        <app-empty>Regulation not found.</app-empty>
      }
    </app-page>
  `,
  styles: `
    :host { display: block; }
  `,
})
export class RegulationPageComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly regulationApi = inject(RegulationApiService);
  private readonly transloco = inject(TranslocoService);

  readonly loading = signal(true);
  readonly content = signal<RegulationContentOut | null>(null);

  private langSub?: Subscription;
  private slug = '';

  ngOnInit(): void {
    this.slug = this.route.snapshot.data['slug'] ?? this.route.snapshot.params['slug'] ?? 'general';
    this.loadContent(this.transloco.getActiveLang());

    this.langSub = this.transloco.langChanges$.subscribe((lang) => {
      this.loadContent(lang);
    });
  }

  ngOnDestroy(): void {
    this.langSub?.unsubscribe();
  }

  private loadContent(lang: string): void {
    this.loading.set(true);
    this.regulationApi.getPage(this.slug, lang).subscribe({
      next: (data) => {
        this.content.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.content.set(null);
        this.loading.set(false);
      },
    });
  }
}
