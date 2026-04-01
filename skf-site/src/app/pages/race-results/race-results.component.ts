import { Component } from '@angular/core';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-race-results',
  imports: [PageIntroComponent, PageLayoutComponent],
  templateUrl: './race-results.component.html',
  styleUrl: './race-results.component.scss'
})
export class RaceResultsComponent {}
