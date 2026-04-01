import { Component } from '@angular/core';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-skf-history',
  imports: [PageIntroComponent, PageLayoutComponent],
  templateUrl: './skf-history.component.html',
  styleUrl: './skf-history.component.scss'
})
export class SkfHistoryComponent {}
