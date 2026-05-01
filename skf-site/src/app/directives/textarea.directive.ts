import { Directive, input } from '@angular/core';

@Directive({
  selector: 'textarea[appTextarea]',
  host: {
    'class': 'app-textarea',
    '[class.app-textarea--sm]': 'size() === "sm"',
  },
})
export class TextareaDirective {
  readonly size = input<'md' | 'sm'>('md');
}
