import { Component, input } from '@angular/core';

@Component({
  selector: 'app-page-intro',
  standalone: true,
  templateUrl: './page-intro.component.html',
  styleUrl: './page-intro.component.scss',
})
export class PageIntroComponent {
  readonly title = input.required<string>();
  readonly subtitle = input<string>();
}
