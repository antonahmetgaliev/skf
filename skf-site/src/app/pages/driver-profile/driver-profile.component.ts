import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { DriverChampionshipResult, DriverPublic, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-driver-profile',
  imports: [DatePipe, DecimalPipe, RouterLink, BtnComponent, CardComponent, EmptyComponent, PageLayoutComponent],
  templateUrl: './driver-profile.component.html',
  styleUrl: './driver-profile.component.scss',
})
export class DriverProfileComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly profileApi = inject(ProfileApiService);

  readonly driver = signal<DriverPublic | null>(null);
  readonly error = signal('');
  readonly championshipResults = signal<DriverChampionshipResult[]>([]);

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    this.profileApi.getPublicDriver(id).subscribe({
      next: (d) => {
        this.driver.set(d);
        if (d.simgridDriverId != null) {
          this.profileApi.getDriverChampionshipResults(d.simgridDriverId).subscribe({
            next: (results) => this.championshipResults.set(results),
          });
        }
      },
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

  getPositionBadge(result: DriverChampionshipResult): string | null {
    if (result.dsq) return null;
    if (result.position === 1) return 'champion';
    if (result.position === 2) return 'top2';
    if (result.position === 3) return 'top3';
    return null;
  }

  getPositionLabel(result: DriverChampionshipResult): string {
    if (result.dsq) return 'DSQ';
    if (result.position === 1) return '🏆 Champion';
    if (result.position === 2) return '🥈 Runner-up';
    if (result.position === 3) return '🥉 3rd Place';
    return result.position != null ? `P${result.position}` : '—';
  }

  isFinishedChampionship(result: DriverChampionshipResult): boolean {
    const today = new Date().toISOString().slice(0, 10);
    if (result.endDate && result.endDate < today) return true;
    if (!result.endDate && !result.acceptingRegistrations) return true;
    return false;
  }
}
