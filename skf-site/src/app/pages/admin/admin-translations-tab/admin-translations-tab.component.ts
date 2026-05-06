import { Component, inject, OnInit, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoService } from '@jsverse/transloco';
import { forkJoin } from 'rxjs';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { InputDirective } from '../../../directives/input.directive';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import { Language, TranslationApiService, TranslationItem } from '../../../services/translation-api.service';

interface TranslationRow {
  key: string;
  values: Record<string, string>; // lang code → value
}

@Component({
  selector: 'app-admin-translations-tab',
  standalone: true,
  imports: [FormsModule, BtnComponent, CardComponent, FormFieldComponent, SpinnerComponent, InputDirective],
  templateUrl: './admin-translations-tab.component.html',
  styleUrl: './admin-translations-tab.component.scss',
})
export class AdminTranslationsTabComponent implements OnInit {
  private readonly api = inject(TranslationApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly languages = signal<Language[]>([]);
  readonly rows = signal<TranslationRow[]>([]);
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
  readonly newValues = signal<Record<string, string>>({});

  // Track modified cells: "lang:key"
  readonly modified = signal<Set<string>>(new Set());

  readonly filteredRows = computed(() => {
    const q = this.filter().toLowerCase();
    if (!q) return this.rows();
    return this.rows().filter(
      (r) =>
        r.key.toLowerCase().includes(q) ||
        Object.values(r.values).some((v) => v.toLowerCase().includes(q))
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
        this.loadAllTranslations();
      },
    });
  }

  loadAllTranslations(): void {
    const langs = this.languages();
    if (langs.length === 0) {
      this.rows.set([]);
      return;
    }

    this.loading.set(true);
    this.modified.set(new Set());

    const requests = langs.reduce(
      (acc, lang) => {
        acc[lang.code] = this.api.getTranslations(lang.code);
        return acc;
      },
      {} as Record<string, ReturnType<TranslationApiService['getTranslations']>>
    );

    forkJoin(requests).subscribe({
      next: (results) => {
        // Collect all unique keys
        const keySet = new Set<string>();
        for (const items of Object.values(results)) {
          for (const item of items) {
            keySet.add(item.key);
          }
        }

        // Build rows
        const rows: TranslationRow[] = [...keySet].sort().map((key) => {
          const values: Record<string, string> = {};
          for (const lang of langs) {
            const item = results[lang.code]?.find((i: TranslationItem) => i.key === key);
            values[lang.code] = item?.value ?? '';
          }
          return { key, values };
        });

        this.rows.set(rows);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  updateValue(key: string, lang: string, value: string): void {
    this.rows.update((list) =>
      list.map((r) =>
        r.key === key ? { ...r, values: { ...r.values, [lang]: value } } : r
      )
    );
    this.modified.update((set) => new Set(set).add(`${lang}:${key}`));
  }

  save(): void {
    const modifiedCells = this.modified();
    if (modifiedCells.size === 0) return;

    // Group modified items by language
    const byLang: Record<string, TranslationItem[]> = {};
    for (const cell of modifiedCells) {
      const [lang, ...keyParts] = cell.split(':');
      const key = keyParts.join(':');
      const row = this.rows().find((r) => r.key === key);
      if (!row) continue;
      if (!byLang[lang]) byLang[lang] = [];
      byLang[lang].push({ key, value: row.values[lang] ?? '' });
    }

    this.saving.set(true);
    this.message.set('');

    const saves = Object.entries(byLang).map(([lang, items]) =>
      this.api.saveTranslations(lang, items)
    );

    forkJoin(saves).subscribe({
      next: () => {
        this.modified.set(new Set());
        this.saving.set(false);
        this.message.set(`Saved ${modifiedCells.size} translation(s).`);
      },
      error: () => {
        this.saving.set(false);
        this.message.set('Failed to save.');
      },
    });
  }

  async deleteKey(key: string): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('admin.deleteTranslationKeyConfirm', { key }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    const langs = this.languages();
    const deletes = langs.map((l) => this.api.deleteKey(l.code, key));
    forkJoin(deletes).subscribe({
      next: () => {
        this.rows.update((list) => list.filter((r) => r.key !== key));
        this.modified.update((set) => {
          const next = new Set(set);
          for (const lang of langs) {
            next.delete(`${lang.code}:${key}`);
          }
          return next;
        });
      },
    });
  }

  addKey(): void {
    const key = this.newKey().trim();
    if (!key) return;

    const vals = this.newValues();
    const langs = this.languages();
    const items: Record<string, TranslationItem[]> = {};
    for (const lang of langs) {
      items[lang.code] = [{ key, value: vals[lang.code] ?? '' }];
    }

    const saves = Object.entries(items).map(([lang, itms]) =>
      this.api.saveTranslations(lang, itms)
    );

    forkJoin(saves).subscribe({
      next: () => {
        const values: Record<string, string> = {};
        for (const lang of langs) {
          values[lang.code] = vals[lang.code] ?? '';
        }
        this.rows.update((list) =>
          [...list, { key, values }].sort((a, b) => a.key.localeCompare(b.key))
        );
        this.newKey.set('');
        this.newValues.set({});
        this.showAddKey.set(false);
      },
    });
  }

  updateNewValue(lang: string, value: string): void {
    this.newValues.update((v) => ({ ...v, [lang]: value }));
  }

  addLanguage(): void {
    const code = this.newLangCode().trim().toLowerCase();
    const name = this.newLangName().trim();
    if (!code || !name) return;

    this.api.addLanguage(code, name).subscribe({
      next: (lang) => {
        this.languages.update((list) => [...list, lang]);
        // Add empty column to all rows
        this.rows.update((list) =>
          list.map((r) => ({ ...r, values: { ...r.values, [code]: '' } }))
        );
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
        this.rows.update((list) =>
          list.map((r) => {
            const { [code]: _, ...rest } = r.values;
            return { ...r, values: rest };
          })
        );
      },
    });
  }

  exportJson(lang: string): void {
    this.api.exportTranslations(lang).subscribe({
      next: (data) => {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `translations_${lang}.json`;
        a.click();
        URL.revokeObjectURL(url);
      },
    });
  }

  importJson(event: Event, lang: string): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    this.api.importTranslations(lang, file).subscribe({
      next: () => {
        this.message.set(`Import to "${lang}" successful.`);
        this.loadAllTranslations();
        input.value = '';
      },
      error: () => {
        this.message.set('Import failed.');
        input.value = '';
      },
    });
  }
}
