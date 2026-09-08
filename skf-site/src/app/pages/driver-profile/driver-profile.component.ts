import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { DriverPublic, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-driver-profile',
  imports: [DatePipe, RouterLink, TranslocoPipe, BadgeComponent, BtnComponent, CardComponent, EmptyComponent, PageLayoutComponent],
  templateUrl: './driver-profile.component.html',
  styleUrl: './driver-profile.component.scss',
})
export class DriverProfileComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly profileApi = inject(ProfileApiService);

  readonly driver = signal<DriverPublic | null>(null);
  readonly error = signal('');

  ngOnInit(): void {
    // Subscribe (not snapshot) so navigating /drivers/a → /drivers/b reloads.
    this.route.paramMap.subscribe((params) => {
      const id = params.get('id') ?? '';
      this.driver.set(null);
      this.error.set('');
      this.profileApi.getPublicDriver(id).subscribe({
        next: (d) => this.driver.set(d),
        error: () => this.error.set('Driver profile not found.'),
      });
    });
  }
}
