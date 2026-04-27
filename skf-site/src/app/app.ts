import { Component, ElementRef, HostListener, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs/operators';
import { DotdWidgetComponent } from './components/dotd-widget/dotd-widget.component';
import { AuthService } from './services/auth.service';
import { CalendarApiService, Community } from './services/calendar-api.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, DotdWidgetComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly calendarApi = inject(CalendarApiService);

  readonly viewAsCommunities = signal<Community[]>([]);
  readonly regulationsOpen = signal(false);
  readonly regulationsActive = signal(false);
  readonly mobileMenuOpen = signal(false);

  ngOnInit(): void {
    this.auth.loadUser();
    this.loadViewAsCommunities();
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

  private updateRegulationsActive(url: string): void {
    this.regulationsActive.set(url === '/regulations' || url.startsWith('/regulations/') || url.startsWith('/regulations?'));
  }
}
