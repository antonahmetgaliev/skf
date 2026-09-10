import { CookieConsentService } from './cookie-consent.service';

describe('CookieConsentService', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts undecided when nothing is stored', () => {
    const service = new CookieConsentService();
    expect(service.decision()).toBeNull();
    expect(service.undecided()).toBe(true);
  });

  it('accept() grants and stops asking', () => {
    const service = new CookieConsentService();
    service.accept();
    expect(service.decision()).toBe('granted');
    expect(service.undecided()).toBe(false);
  });

  it('decline() denies and stops asking', () => {
    const service = new CookieConsentService();
    service.decline();
    expect(service.decision()).toBe('denied');
    expect(service.undecided()).toBe(false);
  });

  it('remembers the decision across page loads', () => {
    new CookieConsentService().decline();
    expect(new CookieConsentService().decision()).toBe('denied');
  });

  it('reset() brings the banner back', () => {
    const service = new CookieConsentService();
    service.accept();
    service.reset();
    expect(service.undecided()).toBe(true);
    expect(new CookieConsentService().decision()).toBeNull();
  });

  it('ignores a corrupted stored value', () => {
    localStorage.setItem('skf.cookieConsent', 'yes-please');
    expect(new CookieConsentService().decision()).toBeNull();
  });
});
