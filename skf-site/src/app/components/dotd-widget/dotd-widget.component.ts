import {
  Component,
  computed,
  inject,
  OnDestroy,
  OnInit,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../services/auth.service';
import {
  DotdApiService,
  DotdCandidateIn,
  DotdPollOut,
} from '../../services/dotd-api.service';
import {
  ChampionshipListItem,
  ChampionshipStandingsData,
  SimgridApiService,
} from '../../services/simgrid-api.service';

@Component({
  selector: 'app-dotd-widget',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './dotd-widget.component.html',
  styleUrl: './dotd-widget.component.scss',
})
export class DotdWidgetComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly dotd = inject(DotdApiService);
  private readonly simgrid = inject(SimgridApiService);

  // ── core state ────────────────────────────────────────────────────────────
  readonly polls = signal<DotdPollOut[]>([]);
  readonly expanded = signal(false);
  readonly loading = signal(false);

  readonly openPollCount = computed(() => this.polls().filter(p => p.isOpen).length);

  /** True when there is at least one open poll the current viewer hasn't voted in. */
  readonly hasUnvotedOpenPoll = computed(() =>
    this.polls().some(p => p.isOpen && !p.hasVoted),
  );

  // ── create-poll modal ─────────────────────────────────────────────────────
  readonly showCreate = signal(false);
  readonly championships = signal<ChampionshipListItem[]>([]);
  readonly standings = signal<ChampionshipStandingsData | null>(null);

  // form fields (two-way bound via ngModel)
  selectedChampId = 0;
  selectedChampName = '';
  selectedRaceId: number | null = null;
  newRaceName = '';
  newClosesAt = '';
  /** Simgrid driver IDs selected as DOTD candidates */
  readonly selectedDriverIds = signal<Set<number>>(new Set());

  readonly creating = signal(false);
  readonly createError = signal<string | null>(null);

  // ── per-poll voting state ─────────────────────────────────────────────────
  readonly votingPollId = signal<string | null>(null);

  private pollInterval?: ReturnType<typeof setInterval>;
  private readonly STORAGE_KEY = 'dotd_bar_expanded';

  // ── lifecycle ─────────────────────────────────────────────────────────────

  ngOnInit(): void {
    const stored = localStorage.getItem(this.STORAGE_KEY);
    if (stored === 'true') this.expanded.set(true);

    this.loadPolls();
    this.pollInterval = setInterval(() => this.loadPolls(), 30_000);
  }

  ngOnDestroy(): void {
    if (this.pollInterval !== undefined) clearInterval(this.pollInterval);
  }

  // ── public actions ────────────────────────────────────────────────────────

  toggle(): void {
    const next = !this.expanded();
    this.expanded.set(next);
    localStorage.setItem(this.STORAGE_KEY, String(next));
  }

  vote(pollId: string, candidateId: string): void {
    if (this.votingPollId() !== null) return;
    this.votingPollId.set(pollId);
    this.dotd.vote(pollId, candidateId).subscribe({
      next: (updated) => this._replacePoll(updated),
      error: () => {},
      complete: () => this.votingPollId.set(null),
    });
  }

  closePoll(pollId: string): void {
    this.dotd.closePoll(pollId).subscribe({
      next: (updated) => this._replacePoll(updated),
    });
  }

  deletePoll(pollId: string): void {
    this.dotd.deletePoll(pollId).subscribe({
      next: () => this.polls.update(list => list.filter(p => p.id !== pollId)),
    });
  }

  // ── admin create modal ────────────────────────────────────────────────────

  openCreateModal(event: Event): void {
    event.stopPropagation();
    this.showCreate.set(true);
    this.createError.set(null);
    this.selectedChampId = 0;
    this.selectedChampName = '';
    this.selectedRaceId = null;
    this.newRaceName = '';
    // Default closes_at to now + 20 minutes, formatted for datetime-local input
    const defaultClose = new Date(Date.now() + 20 * 60 * 1000);
    const pad = (n: number) => String(n).padStart(2, '0');
    this.newClosesAt = `${defaultClose.getFullYear()}-${pad(defaultClose.getMonth() + 1)}-${pad(defaultClose.getDate())}T${pad(defaultClose.getHours())}:${pad(defaultClose.getMinutes())}`;
    this.selectedDriverIds.set(new Set());
    this.standings.set(null);

    this.simgrid.getChampionships().subscribe({
      next: (list) => this.championships.set(list),
    });
  }

  closeCreateModal(): void {
    this.showCreate.set(false);
  }

  onChampionshipChange(): void {
    // ngModel may coerce the option value to a string — normalise to number.
    const champId = +this.selectedChampId;
    if (!champId) return;
    this.selectedChampId = champId;
    this.standings.set(null);
    this.selectedDriverIds.set(new Set());

    const champ = this.championships().find(c => c.id === champId);
    this.selectedChampName = champ?.name ?? '';

    this.simgrid.getChampionshipStandings(champId).subscribe({
      next: (data) => this.standings.set(data),
    });
  }

  onRaceChange(): void {
    const s = this.standings();
    if (!s) return;
    const race = s.races.find(r => r.id === this.selectedRaceId);
    this.newRaceName = race?.displayName ?? '';
  }

  toggleDriver(simgridDriverId: number): void {
    const current = new Set(this.selectedDriverIds());
    if (current.has(simgridDriverId)) {
      current.delete(simgridDriverId);
    } else {
      current.add(simgridDriverId);
    }
    this.selectedDriverIds.set(current);
  }

  isDriverSelected(simgridDriverId: number): boolean {
    return this.selectedDriverIds().has(simgridDriverId);
  }

  submitCreate(): void {
    this.createError.set(null);
    const s = this.standings();
    if (!this.selectedChampId) {
      this.createError.set('Please select a championship.');
      return;
    }
    if (!this.newClosesAt) {
      this.createError.set('Please set a closing time.');
      return;
    }

    let candidates: DotdCandidateIn[];
    if (s) {
      const selected = s.entries.filter(e =>
        e.id !== null && this.selectedDriverIds().has(e.id),
      );
      if (selected.length < 2) {
        this.createError.set('Select at least 2 drivers.');
        return;
      }
      candidates = selected.map(e => ({
        simgridDriverId: e.id,
        driverName: e.displayName,
        championshipPosition: e.position ?? undefined,
      }));
    } else {
      this.createError.set('Championship standings not loaded.');
      return;
    }

    this.creating.set(true);
    this.dotd
      .createPoll({
        championshipId: +this.selectedChampId,
        championshipName: this.selectedChampName,
        raceId: this.selectedRaceId,
        raceName: this.newRaceName || 'Race',
        closesAt: new Date(this.newClosesAt).toISOString(),
        candidates,
      })
      .subscribe({
        next: (poll) => {
          this.polls.update(list => [poll, ...list]);
          this.showCreate.set(false);
        },
        error: (err) => {
          const detail = err?.error?.detail;
          let msg: string;
          if (Array.isArray(detail)) {
            msg = detail.map((e: { msg: string }) => e.msg).join('; ');
          } else if (typeof detail === 'string') {
            msg = detail;
          } else {
            msg = 'Failed to create poll.';
          }
          this.createError.set(msg);
        },
        complete: () => this.creating.set(false),
      });
  }

  // ── helpers ───────────────────────────────────────────────────────────────

  votePercent(voteCount: number | null, totalVotes: number): number {
    if (voteCount === null || totalVotes === 0) return 0;
    return Math.round((voteCount / totalVotes) * 100);
  }

  private loadPolls(): void {
    this.loading.set(true);
    this.dotd.getPolls().subscribe({
      next: (list) => this.polls.set(list),
      error: () => {},
      complete: () => this.loading.set(false),
    });
  }

  private _replacePoll(updated: DotdPollOut): void {
    this.polls.update(list =>
      list.map(p => (p.id === updated.id ? updated : p)),
    );
  }
}
