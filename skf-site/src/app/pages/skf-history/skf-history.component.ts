import { Component } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-skf-history',
  imports: [TranslocoPipe, PageIntroComponent, PageLayoutComponent],
  templateUrl: './skf-history.component.html',
  styleUrl: './skf-history.component.scss'
})
export class SkfHistoryComponent {}
