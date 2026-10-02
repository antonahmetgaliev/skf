import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class LoadingService {
  private count = 0;
  readonly loading = signal(false);

  show(): void {
    this.count++;
    this.loading.set(true);
  }

  hide(): void {
    this.count = Math.max(0, this.count - 1);
    if (this.count === 0) {
      this.loading.set(false);
    }
  }
}
