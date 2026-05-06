import { DatePipe } from '@angular/common';
import { Component, effect, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { InputDirective } from '../../directives/input.directive';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { CardComponent } from '../../components/card/card.component';
import { ModalComponent } from '../../components/modal/modal.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { AuthService } from '../../services/auth.service';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';
import { DriverPublic, LinkCandidate, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-profile',
  imports: [DatePipe, FormsModule, TranslocoPipe, InputDirective, BadgeComponent, BtnComponent, CardComponent, FormFieldComponent, ModalComponent, PageLayoutComponent, SpinnerComponent],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
})
export class ProfileComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly profileApi = inject(ProfileApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly linkCandidates = signal<LinkCandidate[]>([]);
  readonly loadingCandidates = signal(false);
  readonly showLinkModal = signal(false);
  readonly linking = signal(false);
  readonly linkError = signal('');
  readonly syncingNickname = signal(false);

  readonly linkedDriver = signal<DriverPublic | null>(null);
  readonly loadingDriver = signal(false);

  readonly editingPhoto = signal(false);
  editPhotoValue = '';
  readonly savingPhoto = signal(false);

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

  async unlinkDriver(): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.title'),
      message: this.transloco.translate('profile.unlinkDriverConfirm'),
      confirmLabel: this.transloco.translate('profile.unlink'),
      danger: true,
    });
    if (!ok) return;
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

  isExpired(expiresOn: string): boolean {
    return expiresOn < new Date().toISOString().slice(0, 10);
  }

  syncGuildNickname(): void {
    this.syncingNickname.set(true);
    this.auth.refreshGuildNickname().subscribe({
      next: (user) => {
        this.auth.user.set(user);
        this.syncingNickname.set(false);
      },
      error: async (err) => {
        this.syncingNickname.set(false);
        const detail: string = err?.error?.detail ?? '';
        if (detail.toLowerCase().includes('log out')) {
          const ok = await this.confirmSvc.confirm({
            title: this.transloco.translate('common.confirm.title'),
            message: this.transloco.translate('profile.logoutToRefreshGuildConfirm'),
            confirmLabel: this.transloco.translate('profile.logout'),
            danger: false,
          });
          if (ok) {
            this.auth.logout();
          }
        }
      },
    });
  }

  startEditPhoto(): void {
    this.editPhotoValue = this.linkedDriver()?.photoUrl ?? '';
    this.editingPhoto.set(true);
  }

  cancelEditPhoto(): void {
    this.editingPhoto.set(false);
  }

  savePhoto(): void {
    const url = this.editPhotoValue.trim() || null;
    this.savingPhoto.set(true);
    this.profileApi.updateDriverPhoto(url).subscribe({
      next: (driver) => {
        this.linkedDriver.set(driver);
        this.savingPhoto.set(false);
        this.editingPhoto.set(false);
      },
      error: () => this.savingPhoto.set(false),
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

