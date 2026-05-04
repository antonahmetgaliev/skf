import { Component, inject, OnInit, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { InputDirective } from '../../../directives/input.directive';
import { Language, TranslationApiService, TranslationItem } from '../../../services/translation-api.service';

@Component({
  selector: 'app-admin-translations-tab',
  standalone: true,
  imports: [FormsModule, BtnComponent, CardComponent, FormFieldComponent, SpinnerComponent, InputDirective],
  templateUrl: './admin-translations-tab.component.html',
  styleUrl: './admin-translations-tab.component.scss',
})
export class AdminTranslationsTabComponent implements OnInit {
  private readonly api = inject(TranslationApiService);

  readonly languages = signal<Language[]>([]);
  readonly activeLang = signal('en');
  readonly translations = signal<TranslationItem[]>([]);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly filter = signal('');
  readonly message = signal('');

  // New language form
  readonly showAddLang = signal(false);
  readonly newLangCode = signal('');
  readonly newLangName = signal('');

  // New key form
  readonly showAddKey = signal(false);
  readonly newKey = signal('');
  readonly newValue = signal('');

  // Track modified items
  readonly modified = signal<Set<string>>(new Set());

  readonly filteredTranslations = computed(() => {
    const q = this.filter().toLowerCase();
    if (!q) return this.translations();
    return this.translations().filter(
      (t) => t.key.toLowerCase().includes(q) || t.value.toLowerCase().includes(q)
    );
  });

  readonly hasChanges = computed(() => this.modified().size > 0);

  ngOnInit(): void {
    this.loadLanguages();
  }

  private loadLanguages(): void {
    this.api.getLanguages().subscribe({
      next: (langs) => {
        this.languages.set(langs);
        if (langs.length > 0 && !langs.find((l) => l.code === this.activeLang())) {
          this.activeLang.set(langs[0].code);
        }
        this.loadTranslations();
      },
    });
  }

  loadTranslations(): void {
    this.loading.set(true);
    this.modified.set(new Set());
    this.api.getTranslations(this.activeLang()).subscribe({
      next: (items) => {
        this.translations.set(items);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  switchLang(code: string): void {
    this.activeLang.set(code);
    this.loadTranslations();
  }

  updateValue(key: string, value: string): void {
    this.translations.update((list) =>
      list.map((t) => (t.key === key ? { ...t, value } : t))
    );
    this.modified.update((set) => new Set(set).add(key));
  }

  save(): void {
    const modifiedKeys = this.modified();
    const items = this.translations().filter((t) => modifiedKeys.has(t.key));
    if (items.length === 0) return;

    this.saving.set(true);
    this.message.set('');
    this.api.saveTranslations(this.activeLang(), items).subscribe({
      next: () => {
        this.modified.set(new Set());
        this.saving.set(false);
        this.message.set(`Saved ${items.length} translation(s).`);
      },
      error: () => {
        this.saving.set(false);
        this.message.set('Failed to save.');
      },
    });
  }

  deleteKey(key: string): void {
    this.api.deleteKey(this.activeLang(), key).subscribe({
      next: () => {
        this.translations.update((list) => list.filter((t) => t.key !== key));
        this.modified.update((set) => {
          const next = new Set(set);
          next.delete(key);
          return next;
        });
      },
    });
  }

  addKey(): void {
    const key = this.newKey().trim();
    const value = this.newValue().trim();
    if (!key) return;

    const items: TranslationItem[] = [{ key, value }];
    this.api.saveTranslations(this.activeLang(), items).subscribe({
      next: () => {
        this.translations.update((list) => [...list, { key, value }].sort((a, b) => a.key.localeCompare(b.key)));
        this.newKey.set('');
        this.newValue.set('');
        this.showAddKey.set(false);
      },
    });
  }

  addLanguage(): void {
    const code = this.newLangCode().trim().toLowerCase();
    const name = this.newLangName().trim();
    if (!code || !name) return;

    this.api.addLanguage(code, name).subscribe({
      next: (lang) => {
        this.languages.update((list) => [...list, lang]);
        this.newLangCode.set('');
        this.newLangName.set('');
        this.showAddLang.set(false);
      },
    });
  }

  removeLanguage(code: string): void {
    this.api.deleteLanguage(code).subscribe({
      next: () => {
        this.languages.update((list) => list.filter((l) => l.code !== code));
        if (this.activeLang() === code) {
          const remaining = this.languages();
          this.activeLang.set(remaining.length > 0 ? remaining[0].code : '');
          this.loadTranslations();
        }
      },
    });
  }

  exportJson(): void {
    this.api.exportTranslations(this.activeLang()).subscribe({
      next: (data) => {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `translations_${this.activeLang()}.json`;
        a.click();
        URL.revokeObjectURL(url);
      },
    });
  }

  importJson(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    this.api.importTranslations(this.activeLang(), file).subscribe({
      next: () => {
        this.message.set('Import successful.');
        this.loadTranslations();
        input.value = '';
      },
      error: () => {
        this.message.set('Import failed.');
        input.value = '';
      },
    });
  }
}
