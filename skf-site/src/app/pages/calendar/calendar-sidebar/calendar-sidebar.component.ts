import { Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { BtnComponent } from '../../../components/btn/btn.component';
import { SelectDirective } from '../../../directives/select.directive';
import { Community } from '../../../services/calendar-api.service';

@Component({
  selector: 'app-calendar-sidebar',
  imports: [FormsModule, TranslocoPipe, BtnComponent, SelectDirective],
  templateUrl: './calendar-sidebar.component.html',
  styleUrl: './calendar-sidebar.component.scss',
})
export class CalendarSidebarComponent {
  readonly communities = input.required<Community[]>();
  readonly selectedCommunityIds = input.required<ReadonlySet<string>>();
  readonly simulators = input.required<string[]>();
  readonly selectedSimulator = input.required<string | null>();
  readonly hasActiveFilters = input(false);

  readonly toggleCommunity = output<string | null>(); // null = "All"
  readonly simulatorChange = output<string | null>();
  readonly clearFilters = output<void>();
  readonly requestJoin = output<void>();
  readonly close = output<void>();

  readonly allSelected = computed(() => this.selectedCommunityIds().size === 0);

  isSelected(id: string): boolean {
    return this.selectedCommunityIds().has(id);
  }
}
