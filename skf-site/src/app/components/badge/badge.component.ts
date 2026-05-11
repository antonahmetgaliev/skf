import { Component, HostBinding, input } from '@angular/core';

export type BadgeVariant =
  | 'live' | 'ended'
  | 'open' | 'closed'
  | 'pending' | 'resolved' | 'applied' | 'bwp-pending'
  | 'upcoming' | 'past' | 'ongoing' | 'future'
  | 'completed'
  | 'role-super-admin' | 'role-admin' | 'role-community-manager'
  | 'role-moderator' | 'role-judge' | 'role-driver'
  | 'blocked';

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
