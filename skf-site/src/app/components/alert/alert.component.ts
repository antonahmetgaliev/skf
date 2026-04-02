import { Component, HostBinding, input } from '@angular/core';

@Component({
  selector: 'app-alert',
  standalone: true,
  template: '<ng-content />',
  styleUrl: './alert.component.scss',
})
export class AlertComponent {
  readonly variant = input<'info' | 'warning' | 'error' | 'success'>('info');

  @HostBinding('class')
  get hostClass(): string {
    return `alert alert--${this.variant()}`;
  }
}
