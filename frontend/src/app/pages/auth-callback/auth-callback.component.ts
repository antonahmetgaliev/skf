import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { AuthService } from '../../services/auth.service';
import { CallbackError, parseCallbackFragment } from './auth-callback';

/** Where the Discord login lands: turns the refresh token in the URL into a login. */
@Component({
  selector: 'app-auth-callback',
  imports: [TranslocoPipe, BtnComponent, CardComponent, PageLayoutComponent, SpinnerComponent],
  templateUrl: './auth-callback.component.html',
  styleUrl: './auth-callback.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuthCallbackComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly error = signal<CallbackError | null>(null);

  async ngOnInit(): Promise<void> {
    const outcome = parseCallbackFragment(window.location.hash);
    // The token must not stay in the address bar or the history.
    history.replaceState(null, '', window.location.pathname);

    if ('error' in outcome) {
      this.error.set(outcome.error);
      return;
    }
    if (await this.auth.completeLogin(outcome.token)) {
      await this.router.navigateByUrl(this.auth.takeReturnUrl(), { replaceUrl: true });
    } else {
      this.error.set('failed');
    }
  }
}
