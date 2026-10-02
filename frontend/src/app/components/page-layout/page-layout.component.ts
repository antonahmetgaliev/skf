import { Component } from '@angular/core';

@Component({
  selector: 'app-page',
  standalone: true,
  template: '<ng-content />',
  styleUrl: './page-layout.component.scss',
})
export class PageLayoutComponent {}
