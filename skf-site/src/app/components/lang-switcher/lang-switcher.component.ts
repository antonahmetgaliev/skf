import { Component, inject, OnInit, signal } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';

@Component({
  selector: 'app-lang-switcher',
  standalone: true,
  template: `
    <button
      type="button"
      class="lang-switcher-btn"
      (click)="toggle()"
      [attr.aria-label]="'Switch language'"
    >
      {{ activeLang().toUpperCase() }}
    </button>
  `,
  styles: [`
    .lang-switcher-btn {
      background: transparent;
      border: 1px solid rgba(255, 255, 255, 0.3);
      color: inherit;
      padding: 4px 8px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.5px;
      transition: border-color 0.2s, background 0.2s;

      &:hover {
        border-color: rgba(255, 255, 255, 0.6);
        background: rgba(255, 255, 255, 0.1);
      }
    }
  `],
})
export class LangSwitcherComponent implements OnInit {
  private readonly transloco = inject(TranslocoService);
  readonly activeLang = signal(this.transloco.getActiveLang());

  private readonly STORAGE_KEY = 'skf_lang';

  ngOnInit(): void {
    const stored = localStorage.getItem(this.STORAGE_KEY);
    if (stored && (this.transloco.getAvailableLangs() as string[]).includes(stored)) {
      this.transloco.setActiveLang(stored);
      this.activeLang.set(stored);
    }
  }

  toggle(): void {
    const langs = this.transloco.getAvailableLangs() as string[];
    const currentIndex = langs.indexOf(this.activeLang());
    const next = langs[(currentIndex + 1) % langs.length];
    this.transloco.setActiveLang(next);
    this.activeLang.set(next);
    localStorage.setItem(this.STORAGE_KEY, next);
  }
}
