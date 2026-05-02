import { Directive, input } from '@angular/core';

@Directive({
  selector: 'select[appSelect]',
  host: {
    'class': 'app-select',
    '[class.app-select--sm]': 'size() === "sm"',
  },
})
export class SelectDirective {
  readonly size = input<'md' | 'sm'>('md');
}
