import { Component, ElementRef, HostListener, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs/operators';
import { DotdWidgetComponent } from './components/dotd-widget/dotd-widget.component';
import { AuthService } from './services/auth.service';

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

  readonly regulationsOpen = signal(false);
  readonly regulationsActive = signal(false);

  ngOnInit(): void {
    this.auth.loadUser();
    this.updateRegulationsActive(this.router.url);
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => {
        this.updateRegulationsActive(e.urlAfterRedirects);
        this.regulationsOpen.set(false);
      });
  }

  toggleRegulations(): void {
    this.regulationsOpen.update((v) => !v);
  }

  closeRegulations(): void {
    this.regulationsOpen.set(false);
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
  }

  private updateRegulationsActive(url: string): void {
    this.regulationsActive.set(url === '/regulations' || url.startsWith('/regulations/') || url.startsWith('/regulations?'));
  }
}
