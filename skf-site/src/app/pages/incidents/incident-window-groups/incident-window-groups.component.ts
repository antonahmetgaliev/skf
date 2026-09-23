import { Component, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { BadgeComponent } from '../../../components/badge/badge.component';
import { closesIn, WindowGroup } from './window-groups';

/** Protest windows as an accordion: championship → its rounds. */
@Component({
  selector: 'app-incident-window-groups',
  imports: [TranslocoPipe, BadgeComponent],
  templateUrl: './incident-window-groups.component.html',
  styleUrl: './incident-window-groups.component.scss',
})
export class IncidentWindowGroupsComponent {
  readonly groups = input.required<WindowGroup[]>();
  readonly expanded = input.required<ReadonlySet<string>>();
  readonly activeWindowId = input<string | null>(null);

  readonly toggle = output<string>();
  readonly select = output<string>();

  readonly closesIn = closesIn;
}
