import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import {
  CalendarApiService,
  CalendarEvent,
} from '../../services/calendar-api.service';
import { MediaApiService, YouTubeVideo } from '../../services/media-api.service';
import { toLocalDateStr, toLocalTime } from '../../utils/date';
import { CardComponent } from '../card/card.component';
import { BtnComponent } from '../btn/btn.component';
import { SpinnerComponent } from '../spinner/spinner.component';
import { BadgeComponent } from '../badge/badge.component';

interface WeekRace {
  championshipName: string;
  track: string | null;
  raceName: string | null;
  time: string | null;
  image: string | null;
  date: Date;
  simgridChampionshipId: number | null;
}

interface ChampionshipSummary {
  id: string;
  name: string;
  game: string;
  carClass: string | null;
  image: string | null;
  eventType: 'ongoing' | 'upcoming';
  nextRaceDate: string | null;
  nextRaceTrack: string | null;
  totalRaces: number;
  simgridChampionshipId: number | null;
}

@Component({
  selector: 'app-week-calendar',
  imports: [RouterLink, CardComponent, BtnComponent, SpinnerComponent, BadgeComponent],
  templateUrl: './week-calendar.component.html',
  styleUrl: './week-calendar.component.scss',
})
export class WeekCalendarComponent {
  private readonly calendarApi = inject(CalendarApiService);
  private readonly mediaApi = inject(MediaApiService);

  readonly loading = signal(true);
  readonly todayRaces = signal<WeekRace[]>([]);
  readonly weekRaces = signal<WeekRace[]>([]);
  readonly championships = signal<ChampionshipSummary[]>([]);
  readonly todayBroadcasts = signal<YouTubeVideo[]>([]);

  readonly hasTodayContent = computed(() =>
    this.todayRaces().length > 0 || this.todayBroadcasts().length > 0,
  );

  constructor() {
    this.load();
  }

  formatDate(date: Date): string {
    return date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  formatTime(date: Date): string {
    return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }

  private async load(): Promise<void> {
    try {
      const now = new Date();
      const todayStr = this.toDateStr(now);
      const { monday, sunday } = this.getCurrentWeekBounds(now);

      const [events, broadcasts] = await Promise.all([
        this.fetchEventsForRange(monday, sunday),
        this.loadTodayBroadcasts(),
      ]);

      // Extract all races for the week
      const allWeekRaces = this.extractWeekRaces(events, monday, sunday);

      // Split into today vs rest of week
      const today: WeekRace[] = [];
      const restOfWeek: WeekRace[] = [];

      for (const race of allWeekRaces) {
        if (this.toDateStr(race.date) === todayStr) {
          today.push(race);
        } else if (race.date > now) {
          restOfWeek.push(race);
        }
      }

      this.todayRaces.set(today);
      this.weekRaces.set(restOfWeek);
      this.todayBroadcasts.set(broadcasts);

      // Build championship summaries
      const champs = this.buildChampionshipSummaries(events, todayStr);
      this.championships.set(champs);
    } finally {
      this.loading.set(false);
    }
  }

  private async loadTodayBroadcasts(): Promise<YouTubeVideo[]> {
    try {
      const todayStr = this.toDateStr(new Date());

      const [completed, upcoming] = await Promise.all([
        firstValueFrom(this.mediaApi.getLiveStreams(6)).catch(() => [] as YouTubeVideo[]),
        firstValueFrom(this.mediaApi.getUpcomingStreams(6)).catch(() => [] as YouTubeVideo[]),
      ]);

      // Upcoming streams scheduled for today + today's completed streams
      const todayCompleted = completed.filter(
        (s) => toLocalDateStr(s.publishedAt) === todayStr,
      );

      // Deduplicate by videoId (upcoming → completed transition)
      const seen = new Set<string>();
      const merged: YouTubeVideo[] = [];
      for (const s of [...upcoming, ...todayCompleted]) {
        if (!seen.has(s.videoId)) {
          seen.add(s.videoId);
          merged.push(s);
        }
      }

      return merged;
    } catch {
      return [];
    }
  }

  private getCurrentWeekBounds(now: Date): { monday: Date; sunday: Date } {
    const monday = new Date(now);
    const day = monday.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    monday.setDate(monday.getDate() + diff);
    monday.setHours(0, 0, 0, 0);

    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    sunday.setHours(23, 59, 59, 999);

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

  private extractWeekRaces(events: CalendarEvent[], monday: Date, sunday: Date): WeekRace[] {
    const races: WeekRace[] = [];
    const mondayStr = this.toDateStr(monday);
    const sundayStr = this.toDateStr(sunday);

    for (const ev of events) {
      for (const race of ev.races) {
        if (!race.date) continue;
        const raceDay = toLocalDateStr(race.date);
        if (raceDay >= mondayStr && raceDay <= sundayStr) {
          races.push({
            championshipName: ev.name,
            track: race.track,
            raceName: race.name,
            time: toLocalTime(race.date),
            image: ev.image,
            date: new Date(race.date),
            simgridChampionshipId: ev.simgridChampionshipId,
          });
        }
      }
    }

    races.sort((a, b) => a.date.getTime() - b.date.getTime());
    return races;
  }

  private buildChampionshipSummaries(
    events: CalendarEvent[],
    todayStr: string,
  ): ChampionshipSummary[] {
    const summaries: ChampionshipSummary[] = [];

    for (const ev of events) {
      if (ev.eventType !== 'ongoing' && ev.eventType !== 'upcoming') continue;

      // Find next upcoming race
      let nextRaceDate: string | null = null;
      let nextRaceTrack: string | null = null;

      for (const race of ev.races) {
        if (!race.date) continue;
        const raceDay = toLocalDateStr(race.date);
        if (raceDay >= todayStr) {
          if (!nextRaceDate || race.date < nextRaceDate) {
            nextRaceDate = race.date;
            nextRaceTrack = race.track;
          }
        }
      }

      summaries.push({
        id: ev.id,
        name: ev.name,
        game: ev.game,
        carClass: ev.carClass,
        image: ev.image,
        eventType: ev.eventType as 'ongoing' | 'upcoming',
        nextRaceDate,
        nextRaceTrack,
        totalRaces: ev.races.length,
        simgridChampionshipId: ev.simgridChampionshipId,
      });
    }

    // Sort: ongoing first, then by next race date
    summaries.sort((a, b) => {
      if (a.eventType !== b.eventType) {
        return a.eventType === 'ongoing' ? -1 : 1;
      }
      if (a.nextRaceDate && b.nextRaceDate) {
        return a.nextRaceDate.localeCompare(b.nextRaceDate);
      }
      return a.nextRaceDate ? -1 : 1;
    });

    return summaries;
  }

  formatChampDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  }

  private toDateStr(date: Date): string {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }
}
