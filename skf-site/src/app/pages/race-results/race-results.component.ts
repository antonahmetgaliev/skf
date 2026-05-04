import { Component } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-race-results',
  imports: [TranslocoPipe, PageIntroComponent, PageLayoutComponent],
  templateUrl: './race-results.component.html',
  styleUrl: './race-results.component.scss'
})
export class RaceResultsComponent {}
