import { Component } from '@angular/core';
import { CardComponent } from '../../../components/card/card.component';
import { PageIntroComponent } from '../../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-regulations-iracing-league',
  imports: [PageIntroComponent, PageLayoutComponent, CardComponent],
  templateUrl: './iracing-league.component.html',
  styleUrl: '../regulations.component.scss'
})
export class RegulationsIracingLeagueComponent {}
