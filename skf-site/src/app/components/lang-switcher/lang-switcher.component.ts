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
      background: var(--gold);
      border: 1px solid var(--gold);
      color: var(--text-on-gold);
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.5px;
      transition: background 0.2s, border-color 0.2s, transform 0.1s;

      &:hover {
        background: var(--gold-deep);
        border-color: var(--gold-deep);
      }

      &:active {
        transform: translateY(1px);
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
