import { Component } from '@angular/core';
import { CardComponent } from '../../../components/card/card.component';
import { PageIntroComponent } from '../../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-regulations-nascar-general',
  imports: [PageIntroComponent, PageLayoutComponent, CardComponent],
  templateUrl: './nascar-general.component.html',
  styleUrl: '../regulations.component.scss'
})
export class RegulationsNascarGeneralComponent {}
