import { Component } from '@angular/core';

@Component({
  selector: 'app-empty',
  standalone: true,
  template: '<p class="empty-msg"><ng-content /></p>',
  styleUrl: './empty.component.scss',
})
export class EmptyComponent {}
