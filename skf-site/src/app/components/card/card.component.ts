import { Component, HostBinding, input } from '@angular/core';

@Component({
  selector: 'app-card',
  standalone: true,
  templateUrl: './card.component.html',
  styleUrl: './card.component.scss',
})
export class CardComponent {
  readonly animated = input(false);

  @HostBinding('class.animated')
  get isAnimated(): boolean {
    return this.animated();
  }
}
