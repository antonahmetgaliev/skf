import { Component, input } from '@angular/core';

@Component({
  selector: 'app-form-field',
  standalone: true,
  template: `
    @if (label()) {
      <label class="form-field__label" [attr.for]="fieldId() || null">{{ label() }}</label>
    }
    <ng-content />
    @if (error()) {
      <p class="form-field__error">{{ error() }}</p>
    }
  `,
  styleUrl: './form-field.component.scss',
})
export class FormFieldComponent {
  readonly label = input<string>();
  readonly fieldId = input<string>();
  readonly error = input<string>();
}
