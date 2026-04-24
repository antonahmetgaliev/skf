import { Component, input, output } from '@angular/core';

@Component({
  selector: 'app-toggle',
  standalone: true,
  template: `
    <div class="toggle">
      @for (option of options(); track option.key) {
        <button
          class="toggle-option"
          type="button"
          [class.active]="activeKey() === option.key"
          (click)="keyChange.emit(option.key)"
        >{{ option.label }}</button>
      }
    </div>
  `,
  styleUrl: './toggle.component.scss',
})
export class ToggleComponent {
  readonly options = input.required<{ key: string; label: string }[]>();
  readonly activeKey = input.required<string>();
  readonly keyChange = output<string>();
}
