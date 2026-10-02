import { TestBed } from '@angular/core/testing';
import { TranslocoService } from '@jsverse/transloco';
import { of } from 'rxjs';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';
import { IncidentsApiService, VerdictRule } from '../../services/incidents-api.service';
import { IncidentRulesStore } from './incident-rules.store';

function rule(id: string, overrides: Partial<VerdictRule> = {}): VerdictRule {
  return { id, verdict: id, defaultBwp: 0, sortOrder: 0, isDefault: false, ...overrides };
}

function setup(rules: VerdictRule[], confirmed = true) {
  const api = {
    getVerdictRules: vi.fn(() => of(rules)),
    updateVerdictRule: vi.fn(() => of({})),
    reorderVerdictRules: vi.fn(() => of([])),
    deleteVerdictRule: vi.fn(() => of(undefined)),
  };
  TestBed.configureTestingModule({
    providers: [
      IncidentRulesStore,
      { provide: IncidentsApiService, useValue: api },
      { provide: ConfirmDialogService, useValue: { confirm: async () => confirmed } },
      { provide: TranslocoService, useValue: { translate: (k: string) => k } },
    ],
  });
  const store = TestBed.inject(IncidentRulesStore);
  return { store, api };
}

describe('IncidentRulesStore', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('exposes the default rule', async () => {
    const { store } = setup([rule('warning'), rule('no-action', { isDefault: true })]);
    await store.loadVerdictRules();
    expect(store.defaultRule()?.id).toBe('no-action');
  });

  it('only saves whole, non-negative, changed BWP values', async () => {
    const { store, api } = setup([]);
    const r = rule('r', { defaultBwp: 2 });
    for (const value of ['-1', '1.5', 'abc', '2']) await store.saveRuleBwp(r, value);
    expect(api.updateVerdictRule).not.toHaveBeenCalled();
    await store.saveRuleBwp(r, '3');
    expect(api.updateVerdictRule).toHaveBeenCalledWith('r', { defaultBwp: 3 });
  });

  it('swaps neighbours when moving a rule and ignores moves past the ends', async () => {
    const { store, api } = setup([rule('a'), rule('b'), rule('c')]);
    await store.loadVerdictRules();
    await store.moveRule(0, -1);
    await store.moveRule(2, 1);
    expect(api.reorderVerdictRules).not.toHaveBeenCalled();
    await store.moveRule(1, 1);
    expect(api.reorderVerdictRules).toHaveBeenCalledWith(['a', 'c', 'b']);
  });

  it('does not delete when the confirmation is declined', async () => {
    const { store, api } = setup([], false);
    await store.deleteVerdictRule('r');
    expect(api.deleteVerdictRule).not.toHaveBeenCalled();
  });
});
