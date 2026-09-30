import { TestBed } from '@angular/core/testing';
import { TranslocoService } from '@jsverse/transloco';
import { of, throwError } from 'rxjs';
import { CalendarApiService } from '../../../services/calendar-api.service';
import { CommunityRequestModalComponent } from './community-request-modal.component';

function setup(requestCommunity: CalendarApiService['requestCommunity']) {
  TestBed.configureTestingModule({
    providers: [
      { provide: CalendarApiService, useValue: { requestCommunity } },
      { provide: TranslocoService, useValue: { translate: (key: string) => key } },
    ],
  });
  return TestBed.runInInjectionContext(() => new CommunityRequestModalComponent());
}

function fill(c: CommunityRequestModalComponent) {
  c.name.set('  Night Racers ');
  c.discordUrl.set(' ');
  c.description.set('Weekly GT3 races on Fridays');
}

describe('CommunityRequestModalComponent', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('needs a name and a description before it can submit', () => {
    const c = setup(vi.fn());
    expect(c.canSubmit()).toBe(false);
    c.name.set('N');
    c.description.set('Long enough text');
    expect(c.canSubmit()).toBe(false);
    fill(c);
    expect(c.canSubmit()).toBe(true);
  });

  it('sends trimmed values and shows the confirmation', async () => {
    const request = vi.fn().mockReturnValue(of(undefined));
    const c = setup(request);
    fill(c);
    await c.submit();
    expect(request).toHaveBeenCalledWith({
      name: 'Night Racers',
      discordUrl: null,
      description: 'Weekly GT3 races on Fridays',
    });
    expect(c.sent()).toBe(true);
    expect(c.submitting()).toBe(false);
  });

  it('explains the rate limit on 429', async () => {
    const c = setup(vi.fn().mockReturnValue(throwError(() => ({ status: 429 }))));
    fill(c);
    await c.submit();
    expect(c.error()).toBe('calendar.requestCommunityTooSoon');
    expect(c.sent()).toBe(false);
  });

  it('starts empty every time it opens', () => {
    const c = setup(vi.fn());
    fill(c);
    c.sent.set(true);
    c.open.set(true);
    TestBed.tick();
    expect([c.name(), c.description(), c.sent()]).toEqual(['', '', false]);
  });
});
