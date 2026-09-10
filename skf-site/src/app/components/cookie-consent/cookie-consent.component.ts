import { Component, computed, inject } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { AnalyticsService } from '../../services/analytics.service';
import { CookieConsentService } from '../../services/cookie-consent.service';
import { BtnComponent } from '../btn/btn.component';

@Component({
  selector: 'app-cookie-consent',
  standalone: true,
  imports: [BtnComponent, TranslocoPipe],
  templateUrl: './cookie-consent.component.html',
  styleUrl: './cookie-consent.component.scss',
})
export class CookieConsentComponent {
  private readonly consent = inject(CookieConsentService);
  private readonly analytics = inject(AnalyticsService);

  /** Only ask when there is something to consent to and the visitor has not answered yet. */
  readonly visible = computed(() => this.analytics.available() && this.consent.undecided());

  accept(): void {
    this.consent.accept();
  }

  decline(): void {
    this.consent.decline();
  }
}
