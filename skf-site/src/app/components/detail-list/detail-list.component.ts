import { Component, HostBinding, input } from '@angular/core';

@Component({
  selector: 'app-detail-list',
  standalone: true,
  template: '<dl class="detail-list"><ng-content /></dl>',
  styleUrl: './detail-list.component.scss',
})
export class DetailListComponent {
  readonly labelWidth = input('100px');

  @HostBinding('style.--dl-label-width')
  get labelWidthVar(): string {
    return this.labelWidth();
  }
}
