import { Component, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

@Component({
  selector: 'app-tabs',
  standalone: true,
  imports: [TranslocoPipe],
  template: `
    <div class="tabs">
      @for (tab of tabs(); track tab.key) {
        <button
          class="tab"
          type="button"
          [class.active]="activeTab() === tab.key"
          (click)="tabChange.emit(tab.key)"
        >{{ tab.label | transloco }}</button>
      }
    </div>
  `,
  styleUrl: './tabs.component.scss',
})
export class TabsComponent {
  readonly tabs = input.required<{ key: string; label: string }[]>();
  readonly activeTab = input.required<string>();
  readonly tabChange = output<string>();
}
