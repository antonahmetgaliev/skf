import { Component, HostListener, inject } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { BtnComponent } from '../btn/btn.component';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';

@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [BtnComponent, TranslocoPipe],
  templateUrl: './confirm-dialog.component.html',
  styleUrl: './confirm-dialog.component.scss',
})
export class ConfirmDialogComponent {
  private readonly svc = inject(ConfirmDialogService);
  readonly options = this.svc.options;

  cancel(): void {
    this.svc.cancel();
  }

  accept(): void {
    this.svc.accept();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.options()) {
      this.svc.cancel();
    }
  }
}
