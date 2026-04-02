import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CardComponent } from '../../components/card/card.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { RecentBroadcastsComponent } from '../../components/recent-broadcasts/recent-broadcasts.component';
import { WeekCalendarComponent } from '../../components/week-calendar/week-calendar.component';

@Component({
  selector: 'app-home-visit',
  imports: [RouterLink, CardComponent, PageLayoutComponent, RecentBroadcastsComponent, WeekCalendarComponent],
  templateUrl: './home-visit.component.html',
  styleUrl: './home-visit.component.scss',
})
export class HomeVisitComponent {}
