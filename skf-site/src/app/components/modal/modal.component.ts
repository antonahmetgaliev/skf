import { Component, input, model } from '@angular/core';

@Component({
  selector: 'app-modal',
  standalone: true,
  templateUrl: './modal.component.html',
  styleUrl: './modal.component.scss',
})
export class ModalComponent {
  readonly title = input.required<string>();
  readonly width = input<'sm' | 'md' | 'lg' | 'xl'>('md');
  readonly open = model.required<boolean>();

  close(): void {
    this.open.set(false);
  }
}
