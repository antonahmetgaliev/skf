import { Component, ElementRef, HostBinding, HostListener, inject, input } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-btn',
  standalone: true,
  template: '<ng-content />',
  styleUrl: './btn.component.scss',
})
export class BtnComponent {
  private readonly router = inject(Router);
  private readonly el = inject(ElementRef);

  readonly variant = input<'accent' | 'primary' | 'danger' | 'ghost' | 'outline'>('accent');
  readonly size = input<'xs' | 'sm' | 'md'>('md');
  readonly routerLink = input<string>();
  readonly disabled = input(false);
  readonly loading = input(false);
  readonly type = input<'button' | 'submit'>('button');

  @HostBinding('class')
  get hostClass(): string {
    return `btn btn--${this.variant()} btn--${this.size()}`;
  }

  @HostBinding('class.btn--disabled')
  get isDisabled(): boolean {
    return this.disabled() || this.loading();
  }

  @HostBinding('attr.tabindex')
  get tabIndex(): number {
    return this.isDisabled ? -1 : 0;
  }

  @HostBinding('attr.role')
  readonly role = 'button';

  @HostListener('click')
  handleClick(): void {
    if (this.isDisabled) return;
    const link = this.routerLink();
    if (link) {
      this.router.navigateByUrl(link);
      return;
    }
    if (this.type() === 'submit') {
      const form = (this.el.nativeElement as HTMLElement).closest('form');
      if (form) {
        form.requestSubmit();
        return;
      }
    }
  }

  @HostListener('keydown.enter')
  @HostListener('keydown.space')
  handleKey(): void {
    this.handleClick();
  }
}
