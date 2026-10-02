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
