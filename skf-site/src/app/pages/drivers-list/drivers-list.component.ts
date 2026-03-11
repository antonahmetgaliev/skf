import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { BwpApiService, Driver } from '../../services/bwp-api.service';

@Component({
  selector: 'app-drivers-list',
  imports: [RouterLink, FormsModule],
  templateUrl: './drivers-list.component.html',
  styleUrl: './drivers-list.component.scss',
})
export class DriversListComponent {
  private readonly api = inject(BwpApiService);

  readonly drivers = signal<Driver[]>([]);
  readonly loading = signal(true);
  readonly search = signal('');

  readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const list = q
      ? this.drivers().filter((d) => d.name.toLowerCase().includes(q))
      : this.drivers();
    return [...list].sort((a, b) => a.name.localeCompare(b.name));
  });

  constructor() {
    this.api.getDrivers().subscribe({
      next: (drivers) => {
        this.drivers.set(drivers);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  getActiveBwp(driver: Driver): number {
    const today = new Date().toISOString().slice(0, 10);
    return driver.points
      .filter((p) => p.expiresOn >= today)
      .reduce((sum, p) => sum + p.points, 0);
  }
}
