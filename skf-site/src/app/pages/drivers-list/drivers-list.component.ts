import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { InputDirective } from '../../directives/input.directive';
import { DriverPublic, ProfileApiService } from '../../services/profile-api.service';

@Component({
  selector: 'app-drivers-list',
  imports: [RouterLink, FormsModule, TranslocoPipe, InputDirective, PageIntroComponent, PageLayoutComponent, SpinnerComponent, EmptyComponent],
  templateUrl: './drivers-list.component.html',
  styleUrl: './drivers-list.component.scss',
})
export class DriversListComponent {
  private readonly api = inject(ProfileApiService);

  readonly drivers = signal<DriverPublic[]>([]);
  readonly loading = signal(true);
  readonly search = signal('');

  readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const list = q
      ? this.drivers().filter(
          (d) =>
            d.name.toLowerCase().includes(q) ||
            (d.simgridDisplayName?.toLowerCase().includes(q) ?? false),
        )
      : this.drivers();
    return [...list].sort((a, b) => a.name.localeCompare(b.name));
  });

  constructor() {
    this.api.getPublicDrivers().subscribe({
      next: (drivers) => {
        this.drivers.set(drivers);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }
}
