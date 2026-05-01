import { Directive, input } from '@angular/core';

@Directive({
  selector: 'input[appInput]',
  host: {
    'class': 'app-input',
    '[class.app-input--sm]': 'size() === "sm"',
  },
})
export class InputDirective {
  readonly size = input<'md' | 'sm'>('md');
}
