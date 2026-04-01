import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { RecentBroadcastsComponent } from '../../components/recent-broadcasts/recent-broadcasts.component';

@Component({
  selector: 'app-home-visit',
  imports: [RouterLink, BtnComponent, CardComponent, PageLayoutComponent, RecentBroadcastsComponent],
  templateUrl: './home-visit.component.html',
  styleUrl: './home-visit.component.scss',
})
export class HomeVisitComponent {}
