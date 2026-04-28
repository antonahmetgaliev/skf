import {
  Component,
  computed,
  inject,
  OnDestroy,
  OnInit,
  signal,
} from '@angular/core';
import { AuthService } from '../../services/auth.service';
import { AlertComponent } from '../alert/alert.component';
import { BadgeComponent } from '../badge/badge.component';
import { BtnComponent } from '../btn/btn.component';
import {
  DotdApiService,
  DotdPollOut,
} from '../../services/dotd-api.service';

@Component({
  selector: 'app-dotd-widget',
  standalone: true,
  imports: [AlertComponent, BadgeComponent, BtnComponent],
  templateUrl: './dotd-widget.component.html',
  styleUrl: './dotd-widget.component.scss',
})
export class DotdWidgetComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly dotd = inject(DotdApiService);
  // ── core state ────────────────────────────────────────────────────────────
  readonly polls = signal<DotdPollOut[]>([]);
  readonly expanded = signal(false);
  readonly loading = signal(false);

  readonly openPollCount = computed(() => this.polls().filter(p => p.isOpen).length);

  /** True when there is at least one open poll the current viewer hasn't voted in. */
  readonly hasUnvotedOpenPoll = computed(() =>
    this.polls().some(p => p.isOpen && !p.hasVoted),
  );

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
