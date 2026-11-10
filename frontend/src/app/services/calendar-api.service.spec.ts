import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { CalendarApiService } from './calendar-api.service';

describe('CalendarApiService communities cache', () => {
  let api: CalendarApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(CalendarApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('fetches the list once for every subscriber', () => {
    api.getCommunities().subscribe();
    api.getCommunities().subscribe();
    http.expectOne('/api/v1/communities').flush([]);
    api.getCommunities().subscribe();
    http.expectNone('/api/v1/communities');
  });

  it('refetches after a community changes', () => {
    api.getCommunities().subscribe();
    http.expectOne('/api/v1/communities').flush([]);

    api.updateCommunity('c1', { name: 'New' }).subscribe();
    http.expectOne('/api/v1/communities/c1').flush({});

    api.getCommunities().subscribe();
    http.expectOne('/api/v1/communities').flush([]);
  });

  it('retries after a failed request', () => {
    api.getCommunities().subscribe({ error: () => undefined });
    http.expectOne('/api/v1/communities').flush(null, { status: 500, statusText: 'Error' });

    api.getCommunities().subscribe();
    http.expectOne('/api/v1/communities').flush([]);
  });
});

describe('CalendarApiService current events', () => {
  let api: CalendarApiService;
  let http: HttpTestingController;
  const events = (r: { url: string }) => r.url === '/api/v1/calendar-events';

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(CalendarApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('asks for one range starting with this year, once for every subscriber', () => {
    api.getCurrentEvents().subscribe();
    api.getCurrentEvents().subscribe();

    const req = http.expectOne(events);
    expect(req.request.params.get('from')).toBe(`${new Date().getFullYear()}-01-01`);
    expect(req.request.params.get('to')).toMatch(/^\d{4}-12-31$/);
    req.flush([]);

    api.getCurrentEvents().subscribe();
    http.expectNone(events);
  });

  it('asks for a whole year by its first and last day', () => {
    api.getYearEvents(2026).subscribe();
    const req = http.expectOne(events);
    expect(req.request.params.get('from')).toBe('2026-01-01');
    expect(req.request.params.get('to')).toBe('2026-12-31');
    req.flush([]);
  });

  it('refetches after a custom championship changes', () => {
    api.getCurrentEvents().subscribe();
    http.expectOne(events).flush([]);

    api.deleteRace('c1', 'r1').subscribe();
    http.expectOne('/api/v1/custom-championships/c1/races/r1').flush(null);

    api.getCurrentEvents().subscribe();
    http.expectOne(events).flush([]);
  });
});
