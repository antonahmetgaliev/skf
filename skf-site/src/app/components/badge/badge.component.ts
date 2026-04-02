import { Component, HostBinding, input } from '@angular/core';

export type BadgeVariant =
  | 'live' | 'ended'
  | 'open' | 'closed'
  | 'pending' | 'resolved' | 'applied' | 'bwp-pending'
  | 'upcoming' | 'past' | 'ongoing' | 'future'
  | 'completed';

@Component({
  selector: 'app-badge',
  standalone: true,
  template: '<ng-content />',
  styleUrl: './badge.component.scss',
})
export class BadgeComponent {
  readonly variant = input<BadgeVariant>('pending');

  @HostBinding('class')
  get hostClass(): string {
    return `badge badge--${this.variant()}`;
  }
}
