import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { LoadingService } from '../../services/loading.service';

/**
 * A thin progress bar pinned to the top of the viewport whenever any HTTP
 * request is in flight.
 *
 * It fades in rather than appearing instantly: most requests finish in well
 * under the fade delay, so quick ones never visibly paint and the page does not
 * flicker on every keystroke-sized call. Slow ones still announce themselves.
 */
@Component({
  selector: 'app-loading-bar',
  standalone: true,
  template: `
    @if (loading.loading()) {
      <div class="loading-bar" role="status" aria-live="polite" aria-label="Loading">
        <span class="loading-bar__track"></span>
      </div>
    }
  `,
  styleUrl: './loading-bar.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoadingBarComponent {
  readonly loading = inject(LoadingService);
}
