import { Component, ElementRef, HostListener, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { filter } from 'rxjs/operators';
import { DotdWidgetComponent } from './components/dotd-widget/dotd-widget.component';
import { AuthService } from './services/auth.service';
import { CalendarApiService, Community } from './services/calendar-api.service';
import { RegulationApiService, RegulationPageListItem } from './services/regulation-api.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, TranslocoPipe, DotdWidgetComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly calendarApi = inject(CalendarApiService);
  private readonly regulationApi = inject(RegulationApiService);
  private readonly transloco = inject(TranslocoService);

  readonly viewAsCommunities = signal<Community[]>([]);
  readonly regulationPages = signal<RegulationPageListItem[]>([]);
  readonly regulationsOpen = signal(false);
  readonly regulationsActive = signal(false);
  readonly mobileMenuOpen = signal(false);

  ngOnInit(): void {
    this.auth.loadUser();
    this.loadViewAsCommunities();
    this.loadRegulationPages(this.transloco.getActiveLang());
    this.transloco.langChanges$.subscribe((lang) => this.loadRegulationPages(lang));
    this.updateRegulationsActive(this.router.url);
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => {
        this.updateRegulationsActive(e.urlAfterRedirects);
        this.regulationsOpen.set(false);
        this.mobileMenuOpen.set(false);
      });
  }

  toggleRegulations(): void {
    this.regulationsOpen.update((v) => !v);
  }

  closeRegulations(): void {
    this.regulationsOpen.set(false);
  }

  toggleMobileMenu(): void {
    this.mobileMenuOpen.update((v) => !v);
    if (!this.mobileMenuOpen()) {
      this.regulationsOpen.set(false);
    }
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.regulationsOpen()) {
      return;
    }
    const target = event.target as Node | null;
    const dropdown = (this.host.nativeElement as HTMLElement).querySelector('.site-nav-dropdown');
    if (dropdown && target && !dropdown.contains(target)) {
      this.regulationsOpen.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.regulationsOpen.set(false);
    this.mobileMenuOpen.set(false);
  }

  private loadViewAsCommunities(): void {
    this.calendarApi.getCommunities().subscribe({
      next: (data) => this.viewAsCommunities.set(data),
    });
  }

  private loadRegulationPages(lang: string): void {
    this.regulationApi.listPages(lang).subscribe({
      next: (pages) => this.regulationPages.set(pages),
    });
  }

  private updateRegulationsActive(url: string): void {
    this.regulationsActive.set(url === '/regulations' || url.startsWith('/regulations/') || url.startsWith('/regulations?'));
  }
}
