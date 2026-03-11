import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DriverPublic, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-driver-profile',
  imports: [DatePipe, RouterLink],
  templateUrl: './driver-profile.component.html',
  styleUrl: './driver-profile.component.scss',
})
export class DriverProfileComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly profileApi = inject(ProfileApiService);

  readonly driver = signal<DriverPublic | null>(null);
  readonly error = signal('');

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    this.profileApi.getPublicDriver(id).subscribe({
      next: (d) => this.driver.set(d),
      error: () => this.error.set('Driver profile not found.'),
    });
  }

  getActiveBwp(driver: DriverPublic): number {
    const today = new Date().toISOString().slice(0, 10);
    return driver.points
      .filter((p) => p.expiresOn >= today)
      .reduce((sum, p) => sum + p.points, 0);
  }

  getActivePoints(driver: DriverPublic) {
    const today = new Date().toISOString().slice(0, 10);
    return driver.points.filter((p) => p.expiresOn >= today);
  }

  getExpiredPoints(driver: DriverPublic) {
    const today = new Date().toISOString().slice(0, 10);
    return driver.points.filter((p) => p.expiresOn < today);
  }

  isExpired(expiresOn: string): boolean {
    return expiresOn < new Date().toISOString().slice(0, 10);
  }
}
