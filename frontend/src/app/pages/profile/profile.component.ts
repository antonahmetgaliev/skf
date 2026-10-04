import { DatePipe } from '@angular/common';
import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { InputDirective } from '../../directives/input.directive';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { AuthService } from '../../services/auth.service';
import { DriverAdminApiService, DriverLink } from '../../services/driver-admin-api.service';
import { DriverPublic, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-profile',
  imports: [
    DatePipe,
    FormsModule,
    TranslocoPipe,
    InputDirective,
    BadgeComponent,
    BtnComponent,
    CardComponent,
    PageLayoutComponent,
    SpinnerComponent,
  ],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
})
export class ProfileComponent {
  readonly auth = inject(AuthService);
  private readonly profileApi = inject(ProfileApiService);
  private readonly driverApi = inject(DriverAdminApiService);

  /** Why the account has no driver; `null` until SimGrid has been asked. */
  readonly linkStatus = signal<DriverLink['status'] | null>(null);

  readonly linkedDriver = signal<DriverPublic | null>(null);
  readonly loadingDriver = signal(false);

  readonly editingPhoto = signal(false);
  editPhotoValue = '';
  readonly savingPhoto = signal(false);

  /** Tracks which user the page was initialised for, so the auth signal
   *  resolving after a hard refresh still triggers initialisation. */
  private initializedForUserId: string | null = null;

  constructor() {
    // /me may still be in flight on a direct page load — react to the
    // user signal instead of reading it once in ngOnInit.
    effect(() => {
      const user = this.auth.user();
      if (!user || this.initializedForUserId === user.id) return;
      this.initializedForUserId = user.id;

      this.refreshUserSilently();

      if (user.driverId) {
        this.loadLinkedDriver();
      } else {
        this.findMyDriver();
      }
    });
  }

  /** Ask SimGrid who this account is: links the driver, or learns why there is none. */
  private findMyDriver(): void {
    this.driverApi.linkMyDriver().subscribe({
      next: (link) => {
        this.linkStatus.set(link.status);
        const user = this.auth.user();
        if (link.driverId && user) {
          this.auth.user.set({ ...user, driverId: link.driverId });
          this.loadLinkedDriver();
        }
      },
      error: () => {},
    });
  }

  /** Refresh the Discord nickname and user snapshot without any button.
   *  Errors (no bot token, Discord hiccup) are silently ignored. */
  private refreshUserSilently(): void {
    this.auth.refreshDiscordNickname().subscribe({
      next: (user) => {
        this.auth.user.set(user);
        if (user.driverId && !this.linkedDriver() && !this.loadingDriver()) {
          this.loadLinkedDriver();
        }
      },
      error: () => {},
    });
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
    this.auth.logout();
  }
}
