import { NgClass } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import {
  CalendarApiService,
  CalendarEvent,
} from '../../services/calendar-api.service';
import { toLocalDateStr, toLocalTime } from '../../utils/date';
import { CardComponent } from '../card/card.component';
import { BtnComponent } from '../btn/btn.component';
import { SpinnerComponent } from '../spinner/spinner.component';

interface WeekDay {
  date: Date;
  dayName: string;
  dayNumber: number;
  isToday: boolean;
  races: WeekRace[];
}

interface WeekRace {
  championshipName: string;
  track: string | null;
  raceName: string | null;
  time: string | null;
  image: string | null;
  simgridChampionshipId: number | null;
}

@Component({
  selector: 'app-week-calendar',
  imports: [NgClass, RouterLink, CardComponent, BtnComponent, SpinnerComponent],
  templateUrl: './week-calendar.component.html',
  styleUrl: './week-calendar.component.scss',
})
export class WeekCalendarComponent {
  private readonly calendarApi = inject(CalendarApiService);

  readonly loading = signal(true);
  readonly weekDays = signal<WeekDay[]>([]);
  readonly nextRace = signal<(WeekRace & { date: Date }) | null>(null);

  readonly featured = computed<{ label: string; race: WeekRace; date: Date } | null>(() => {
    const today = this.weekDays().find((d) => d.isToday && d.races.length > 0);
    if (today) {
      return { label: 'Today\'s Race', race: today.races[0], date: today.date };
    }
    const next = this.nextRace();
    if (next) {
      return { label: 'Next Race', race: next, date: next.date };
    }
    return null;
  });

  readonly hasAnyRaces = computed(() =>
    this.weekDays().some((d) => d.races.length > 0) || this.nextRace() !== null,
  );

  constructor() {
    this.load();
  }

  formatDate(date: Date): string {
    return date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  private async load(): Promise<void> {
    try {
      const now = new Date();
      const { monday, sunday } = this.getCurrentWeekBounds(now);

      // Fetch months that the week spans
      const events = await this.fetchEventsForRange(monday, sunday);

      // Build week days
      const days: WeekDay[] = [];
      for (let i = 0; i < 7; i++) {
        const date = new Date(monday);
        date.setDate(monday.getDate() + i);
        const dayStr = this.toDateStr(date);

        const races = this.extractRacesForDate(events, dayStr);

        days.push({
          date,
          dayName: date.toLocaleDateString('en-US', { weekday: 'short' }),
          dayNumber: date.getDate(),
          isToday: dayStr === this.toDateStr(now),
          races,
        });
      }

      this.weekDays.set(days);

      // Find next upcoming race (today or future, first one chronologically)
      const todayStr = this.toDateStr(now);
      this.nextRace.set(this.findNextRace(events, todayStr));
    } finally {
      this.loading.set(false);
    }
  }

  private getCurrentWeekBounds(now: Date): { monday: Date; sunday: Date } {
    const monday = new Date(now);
    const day = monday.getDay();
    const diff = day === 0 ? -6 : 1 - day; // Monday-based week
    monday.setDate(monday.getDate() + diff);
    monday.setHours(0, 0, 0, 0);

    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);

    return { monday, sunday };
  }

  private async fetchEventsForRange(start: Date, end: Date): Promise<CalendarEvent[]> {
    const months = new Set<string>();
    months.add(`${start.getFullYear()}-${start.getMonth() + 1}`);
    months.add(`${end.getFullYear()}-${end.getMonth() + 1}`);

    const fetches = [...months].map((key) => {
      const [y, m] = key.split('-').map(Number);
      return firstValueFrom(this.calendarApi.getEvents(y, m));
    });

    const results = await Promise.all(fetches);
    // Deduplicate by event id
    const seen = new Set<string>();
    const merged: CalendarEvent[] = [];
    for (const list of results) {
      for (const ev of list) {
        if (!seen.has(ev.id)) {
          seen.add(ev.id);
          merged.push(ev);
        }
      }
    }
    return merged;
  }

  private extractRacesForDate(events: CalendarEvent[], dayStr: string): WeekRace[] {
    const races: WeekRace[] = [];
    for (const ev of events) {
      for (const race of ev.races) {
        if (race.date && toLocalDateStr(race.date) === dayStr) {
          races.push({
            championshipName: ev.name,
            track: race.track,
            raceName: race.name,
            time: toLocalTime(race.date),
            image: ev.image,
            simgridChampionshipId: ev.simgridChampionshipId,
          });
        }
      }
    }
    return races;
  }

  private findNextRace(
    events: CalendarEvent[],
    todayStr: string,
  ): (WeekRace & { date: Date }) | null {
    let closest: { race: WeekRace; date: Date } | null = null;

    for (const ev of events) {
      for (const race of ev.races) {
        if (!race.date) continue;
        const raceDay = toLocalDateStr(race.date);
        if (raceDay >= todayStr) {
          const d = new Date(race.date);
          if (!closest || d < closest.date) {
            closest = {
              date: d,
              race: {
                championshipName: ev.name,
                track: race.track,
                raceName: race.name,
                time: toLocalTime(race.date),
                image: ev.image,
                simgridChampionshipId: ev.simgridChampionshipId,
              },
            };
          }
        }
      }
    }

    return closest ? { ...closest.race, date: closest.date } : null;
  }

  private toDateStr(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }
}
