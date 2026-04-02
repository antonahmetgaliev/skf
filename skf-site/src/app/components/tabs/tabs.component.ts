import { Component, input, output } from '@angular/core';

@Component({
  selector: 'app-tabs',
  standalone: true,
  template: `
    <div class="tabs">
      @for (tab of tabs(); track tab.key) {
        <button
          class="tab"
          type="button"
          [class.active]="activeTab() === tab.key"
          (click)="tabChange.emit(tab.key)"
        >{{ tab.label }}</button>
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
