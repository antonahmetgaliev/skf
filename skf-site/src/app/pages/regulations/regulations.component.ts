import { Component } from '@angular/core';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';

@Component({
  selector: 'app-regulations',
  imports: [PageIntroComponent, PageLayoutComponent, CardComponent],
  templateUrl: './regulations.component.html',
  styleUrl: './regulations.component.scss'
})
export class RegulationsComponent {}
