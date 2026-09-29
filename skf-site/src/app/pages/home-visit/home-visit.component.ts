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

  /** SKF championships running or about to start: ongoing first, then by start date. */
  readonly championships = toSignal(
    this.calendarApi.getCurrentEvents().pipe(
      map((events) =>
        events
          .filter((ev) => ev.source === 'simgrid' && (ev.eventType === 'ongoing' || ev.eventType === 'upcoming'))
          .sort(
            (a, b) =>
              Number(b.eventType === 'ongoing') - Number(a.eventType === 'ongoing') ||
              (a.startDate ?? '9999').localeCompare(b.startDate ?? '9999'),
          ),
      ),
      catchError(() => of([] as CalendarEvent[])),
    ),
    { initialValue: [] as CalendarEvent[] },
  );

  readonly hasChampionships = computed(() => this.championships().length > 0);

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(this.locale.locale, { day: 'numeric', month: 'long' });
  }

  isOngoing(ev: CalendarEvent): boolean {
    return ev.eventType === 'ongoing';
  }

  /** Rounds already raced (a multi-day round counts once it has ended). */
  roundsDone(ev: CalendarEvent): number {
    const now = Date.now();
    return ev.races.filter((r) => {
      const end = r.endDate ?? r.date;
      return end !== null && new Date(end).getTime() < now;
    }).length;
  }

  nextRoundDate(ev: CalendarEvent): string | null {
    const now = Date.now();
    const upcoming = ev.races
      .map((r) => r.date)
      .filter((d): d is string => d !== null && new Date(d).getTime() >= now)
      .sort();
    return upcoming[0] ?? null;
  }
}
