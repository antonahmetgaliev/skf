import { Component, HostListener, inject, input, model } from '@angular/core';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';

@Component({
  selector: 'app-modal',
  standalone: true,
  templateUrl: './modal.component.html',
  styleUrl: './modal.component.scss',
})
export class ModalComponent {
  private readonly confirm = inject(ConfirmDialogService);

  readonly title = input.required<string>();
  readonly width = input<'sm' | 'md' | 'lg' | 'xl'>('md');
  readonly open = model.required<boolean>();

  close(): void {
    this.open.set(false);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    // A confirm dialog stacked on top owns Escape.
    if (this.open() && !this.confirm.options()) {
      this.close();
    }
  }
}
