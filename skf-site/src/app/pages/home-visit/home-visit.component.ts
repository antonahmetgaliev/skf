import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { catchError, map, of } from 'rxjs';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { RecentBroadcastsComponent } from '../../components/recent-broadcasts/recent-broadcasts.component';
import { WeekCalendarComponent } from '../../components/week-calendar/week-calendar.component';
import { SKF_DISCORD_INVITE, SKF_SIMGRID_COMMUNITY } from '../../links';
import { CalendarApiService, CalendarEvent } from '../../services/calendar-api.service';
import { LocaleService } from '../../services/locale.service';

@Component({
  selector: 'app-home-visit',
  imports: [
    RouterLink,
    TranslocoPipe,
    BadgeComponent,
    BtnComponent,
    CardComponent,
    PageLayoutComponent,
    RecentBroadcastsComponent,
    WeekCalendarComponent,
  ],
  templateUrl: './home-visit.component.html',
  styleUrl: './home-visit.component.scss',
})
export class HomeVisitComponent {
  private readonly calendarApi = inject(CalendarApiService);
  private readonly locale = inject(LocaleService);

  readonly simgridUrl = SKF_SIMGRID_COMMUNITY;

  readonly discordUrl = toSignal(
    this.calendarApi.getCommunities().pipe(
      map((list) => list.find((c) => c.isSkf)?.discordUrl || SKF_DISCORD_INVITE),
      catchError(() => of(SKF_DISCORD_INVITE)),
    ),
    { initialValue: SKF_DISCORD_INVITE },
  );

  /** SKF championships currently taking entries, soonest start first. */
  readonly openChampionships = toSignal(
    this.calendarApi.getCurrentEvents().pipe(
      map((events) =>
        events
          .filter((ev) => ev.source === 'simgrid' && ev.acceptingRegistrations && ev.eventType !== 'past')
          .sort((a, b) => (a.startDate ?? '9999').localeCompare(b.startDate ?? '9999')),
      ),
      catchError(() => of([] as CalendarEvent[])),
    ),
    { initialValue: [] as CalendarEvent[] },
  );

  readonly hasOpenChampionships = computed(() => this.openChampionships().length > 0);

  scrollToOpenRegistration(): void {
    document.getElementById('open-registration')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(this.locale.locale, { day: 'numeric', month: 'long' });
  }

  spotsPercent(ev: CalendarEvent): number {
    if (!ev.capacity) return 0;
    return Math.min(100, ((ev.spotsTaken ?? 0) / ev.capacity) * 100);
  }
}
