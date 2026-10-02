import { Injectable, signal } from '@angular/core';

export interface ConfirmDialogOptions {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ConfirmDialogService {
  readonly options = signal<ConfirmDialogOptions | null>(null);
  private resolver: ((value: boolean) => void) | null = null;

  confirm(options: ConfirmDialogOptions): Promise<boolean> {
    if (this.resolver) {
      this.resolver(false);
      this.resolver = null;
    }
    return new Promise<boolean>((resolve) => {
      this.resolver = resolve;
      this.options.set(options);
    });
  }

  accept(): void {
    this.settle(true);
  }

  cancel(): void {
    this.settle(false);
  }

  private settle(value: boolean): void {
    const resolver = this.resolver;
    this.resolver = null;
    this.options.set(null);
    resolver?.(value);
  }
}
