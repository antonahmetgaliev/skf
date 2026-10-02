import { LoadingService } from './loading.service';

describe('LoadingService', () => {
  let service: LoadingService;

  beforeEach(() => {
    service = new LoadingService();
  });

  it('starts with loading = false', () => {
    expect(service.loading()).toBe(false);
  });

  it('show() sets loading to true', () => {
    service.show();
    expect(service.loading()).toBe(true);
  });

  it('hide() after single show() sets loading back to false', () => {
    service.show();
    service.hide();
    expect(service.loading()).toBe(false);
  });

  it('loading stays true while multiple requests are in-flight', () => {
    service.show(); // request 1
    service.show(); // request 2
    service.hide(); // request 1 done
    expect(service.loading()).toBe(true); // request 2 still pending

    service.hide(); // request 2 done
    expect(service.loading()).toBe(false);
  });

  it('extra hide() calls are ignored (count never goes negative)', () => {
    service.hide(); // no-op
    service.hide(); // no-op
    expect(service.loading()).toBe(false);

    service.show();
    service.hide();
    expect(service.loading()).toBe(false);
  });

  it('loading stays false with asymmetric hides then a show/hide pair', () => {
    // Simulate stray hides before any show
    service.hide();
    service.hide();

    service.show();
    service.hide();

    expect(service.loading()).toBe(false);
  });
});
