import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  OnInit,
  output,
  signal,
} from '@angular/core';
import { Observable } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { EmptyComponent } from '../../../components/empty/empty.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { InputDirective } from '../../../directives/input.directive';
import { SelectDirective } from '../../../directives/select.directive';
import { BwpApiService, Driver } from '../../../services/bwp-api.service';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import {
  DriverAdminApiService,
  DriverIssue,
  DriverSyncResult,
} from '../../../services/driver-admin-api.service';

/**
 * Admin tab for driver rows left over from before "a driver is a SimGrid
 * user": rows without a SimGrid id, and rows sharing one. Each is merged into
 * the person's real row, given its SimGrid id, or deleted.
 */
@Component({
  selector: 'app-admin-drivers-tab',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    InputDirective,
    SelectDirective,
    BtnComponent,
    CardComponent,
    EmptyComponent,
    SpinnerComponent,
  ],
  templateUrl: './admin-drivers-tab.component.html',
  styleUrl: './admin-drivers-tab.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminDriversTabComponent implements OnInit {
  private readonly api = inject(DriverAdminApiService);
  private readonly bwpApi = inject(BwpApiService);
  private readonly confirm = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);
  private readonly destroyRef = inject(DestroyRef);

  /** A merge or sync may have moved account links: the users list is stale. */
  readonly changed = output<void>();

  readonly issues = signal<DriverIssue[]>([]);
  readonly drivers = signal<Driver[]>([]);
  readonly loading = signal(false);
  readonly syncing = signal(false);
  readonly syncResult = signal<DriverSyncResult | null>(null);
  readonly error = signal('');

  /** Per driver id: the merge target picked and the SimGrid id typed. */
  readonly mergeTargets = signal<Record<string, string>>({});
  readonly simgridIds = signal<Record<string, string>>({});

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api
      .getIssues()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (issues) => {
          this.issues.set(issues);
          this.mergeTargets.set(
            Object.fromEntries(issues.map((i) => [i.driver.id, i.suggestedTarget?.id ?? ''])),
          );
          this.loading.set(false);
        },
        error: (err) => this.fail(err),
      });
    this.bwpApi
      .getDrivers()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (drivers) => this.drivers.set(drivers) });
  }

  sync(): void {
    this.syncing.set(true);
    this.error.set('');
    this.api
      .sync()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.syncResult.set(result);
          this.syncing.set(false);
          this.changed.emit();
          this.load();
        },
        error: (err) => {
          this.syncing.set(false);
          this.fail(err);
        },
      });
  }

  /** Drivers this row can be folded into: any other row that has a SimGrid id. */
  targetsFor(issue: DriverIssue): Driver[] {
    return this.drivers().filter((d) => d.id !== issue.driver.id && d.simgridDriverId !== null);
  }

  setMergeTarget(driverId: string, targetId: string): void {
    this.mergeTargets.update((m) => ({ ...m, [driverId]: targetId }));
  }

  setSimgridId(driverId: string, value: string): void {
    this.simgridIds.update((m) => ({ ...m, [driverId]: value }));
  }

  async merge(issue: DriverIssue): Promise<void> {
    const targetId = this.mergeTargets()[issue.driver.id];
    const target = this.drivers().find((d) => d.id === targetId);
    if (!target) return;
    const ok = await this.confirm.confirm({
      title: this.transloco.translate('adminDrivers.mergeInto'),
      message: this.transloco.translate('adminDrivers.confirmMerge', {
        source: issue.driver.name,
        target: target.name,
      }),
      danger: true,
    });
    if (!ok) return;
    this.run(this.api.merge(target.id, issue.driver.id));
  }

  saveSimgridId(issue: DriverIssue): void {
    const id = Number(this.simgridIds()[issue.driver.id]);
    if (!Number.isInteger(id) || id <= 0) {
      this.error.set(this.transloco.translate('adminDrivers.invalidSimgridId'));
      return;
    }
    this.run(this.bwpApi.updateDriver(issue.driver.id, { simgridDriverId: id }));
  }

  async remove(issue: DriverIssue): Promise<void> {
    const ok = await this.confirm.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('adminDrivers.confirmDelete', { name: issue.driver.name }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    this.run(this.bwpApi.deleteDriver(issue.driver.id));
  }

  private run(action: Observable<unknown>): void {
    this.error.set('');
    action.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.changed.emit();
        this.load();
      },
      error: (err) => this.fail(err),
    });
  }

  private fail(err: { error?: { detail?: string } }): void {
    this.loading.set(false);
    this.error.set(err?.error?.detail ?? this.transloco.translate('adminDrivers.failed'));
  }
}
