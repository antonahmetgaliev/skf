import { DatePipe } from '@angular/common';
import { Component, effect, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { DriverPublic, LinkCandidate, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-profile',
  imports: [DatePipe, RouterLink],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
})
export class ProfileComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly profileApi = inject(ProfileApiService);

  readonly linkCandidates = signal<LinkCandidate[]>([]);
  readonly loadingCandidates = signal(false);
  readonly showLinkModal = signal(false);
  readonly linking = signal(false);
  readonly linkError = signal('');
  readonly syncingNickname = signal(false);

  readonly linkedDriver = signal<DriverPublic | null>(null);
  readonly loadingDriver = signal(false);

  constructor() {
    effect((onCleanup) => {
      if (typeof document === 'undefined') return;
      document.body.style.overflow = this.showLinkModal() ? 'hidden' : '';
      onCleanup(() => { document.body.style.overflow = ''; });
    });
  }

  ngOnInit(): void {
    const user = this.auth.user();
    if (!user) return;

    if (user.driverId) {
      this.loadLinkedDriver();
    } else {
      const skipped = localStorage.getItem(`link-skipped:${user.id}`);
      if (!skipped) {
        this.fetchLinkCandidates();
      }
    }
  }

  private loadLinkedDriver(): void {
    this.loadingDriver.set(true);
    this.profileApi.getMyDriver().subscribe({
      next: (driver) => {
        this.linkedDriver.set(driver);
        this.loadingDriver.set(false);
      },
      error: () => this.loadingDriver.set(false),
    });
  }

  fetchLinkCandidates(): void {
    this.loadingCandidates.set(true);
    this.profileApi.getLinkCandidates().subscribe({
      next: (candidates) => {
        this.loadingCandidates.set(false);
        if (candidates.length > 0) {
          this.linkCandidates.set(candidates);
          this.showLinkModal.set(true);
        }
      },
      error: () => this.loadingCandidates.set(false),
    });
  }

  confirmLink(driverId: string): void {
    this.linking.set(true);
    this.linkError.set('');
    this.profileApi.linkDriver(driverId).subscribe({
      next: () => {
        this.linking.set(false);
        this.showLinkModal.set(false);
        this.auth.loadUser();
        this.loadLinkedDriver();
      },
      error: (err) => {
        this.linking.set(false);
        this.linkError.set(err?.error?.detail ?? 'Failed to link driver.');
      },
    });
  }

  skipLink(): void {
    const user = this.auth.user();
    if (user) {
      localStorage.setItem(`link-skipped:${user.id}`, '1');
    }
    this.showLinkModal.set(false);
  }

  unlinkDriver(): void {
    if (!window.confirm('Unlink your driver profile?')) return;
    this.profileApi.unlinkDriver().subscribe({
      next: () => {
        this.linkedDriver.set(null);
        this.auth.loadUser();
      },
    });
  }

  getActiveBwp(driver: DriverPublic): number {
    const today = new Date().toISOString().slice(0, 10);
    return driver.points
      .filter((p) => p.expiresOn >= today)
      .reduce((sum, p) => sum + p.points, 0);
  }

  syncGuildNickname(): void {
    this.syncingNickname.set(true);
    this.auth.refreshGuildNickname().subscribe({
      next: (user) => {
        this.auth.user.set(user);
        this.syncingNickname.set(false);
      },
      error: () => this.syncingNickname.set(false),
    });
  }

  logout(): void {
    const user = this.auth.user();
    if (user) {
      localStorage.removeItem(`link-skipped:${user.id}`);
    }
    this.auth.logout();
  }
}

