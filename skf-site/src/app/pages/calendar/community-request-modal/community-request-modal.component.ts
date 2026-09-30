import { Component, computed, effect, inject, model, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';
import { BtnComponent } from '../../../components/btn/btn.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { ModalComponent } from '../../../components/modal/modal.component';
import { InputDirective } from '../../../directives/input.directive';
import { TextareaDirective } from '../../../directives/textarea.directive';
import { CalendarApiService } from '../../../services/calendar-api.service';

/** Form that asks the admins (via Discord) to add a new community to the calendar. */
@Component({
  selector: 'app-community-request-modal',
  imports: [
    FormsModule,
    TranslocoPipe,
    BtnComponent,
    FormFieldComponent,
    ModalComponent,
    InputDirective,
    TextareaDirective,
  ],
  templateUrl: './community-request-modal.component.html',
  styleUrl: './community-request-modal.component.scss',
})
export class CommunityRequestModalComponent {
  private readonly calendarApi = inject(CalendarApiService);
  private readonly transloco = inject(TranslocoService);

  readonly open = model(false);

  readonly name = signal('');
  readonly discordUrl = signal('');
  readonly description = signal('');
  readonly submitting = signal(false);
  readonly error = signal<string | null>(null);
  readonly sent = signal(false);

  readonly canSubmit = computed(
    () =>
      !this.submitting() &&
      this.name().trim().length >= 2 &&
      this.description().trim().length >= 10,
  );

  constructor() {
    // Every opening starts with an empty form.
    effect(() => {
      if (this.open()) untracked(() => this.reset());
    });
  }

  async submit(): Promise<void> {
    if (!this.canSubmit()) return;
    this.submitting.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(
        this.calendarApi.requestCommunity({
          name: this.name().trim(),
          discordUrl: this.discordUrl().trim() || null,
          description: this.description().trim(),
        }),
      );
      this.sent.set(true);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      const key =
        status === 429 ? 'calendar.requestCommunityTooSoon' : 'calendar.requestCommunityError';
      this.error.set(this.transloco.translate(key));
    } finally {
      this.submitting.set(false);
    }
  }

  private reset(): void {
    this.name.set('');
    this.discordUrl.set('');
    this.description.set('');
    this.error.set(null);
    this.sent.set(false);
  }
}
