import { Component, inject, OnInit, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoService } from '@jsverse/transloco';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { EmptyComponent } from '../../../components/empty/empty.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { InputDirective } from '../../../directives/input.directive';
import { MarkdownPipe } from '../../../pipes/markdown.pipe';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import {
  RegulationApiService,
  RegulationContentUpdate,
  RegulationPageOut,
} from '../../../services/regulation-api.service';

@Component({
  selector: 'app-admin-regulations-tab',
  standalone: true,
  imports: [
    FormsModule,
    BtnComponent,
    CardComponent,
    EmptyComponent,
    FormFieldComponent,
    SpinnerComponent,
    InputDirective,
    MarkdownPipe,
  ],
  templateUrl: './admin-regulations-tab.component.html',
  styleUrl: './admin-regulations-tab.component.scss',
})
export class AdminRegulationsTabComponent implements OnInit {
  private readonly api = inject(RegulationApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly pages = signal<RegulationPageOut[]>([]);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly message = signal('');
  readonly selectedId = signal<string | null>(null);
  readonly activeLang = signal('en');
  readonly showPreview = signal(false);

  // New page form
  readonly showNewForm = signal(false);
  newSlug = '';
  newSortOrder = 0;

  readonly selectedPage = computed(() => {
    const id = this.selectedId();
    return this.pages().find((p) => p.id === id) ?? null;
  });

  // Edit buffer: Record<lang, { title, subtitle, content }>
  editContents: Record<string, RegulationContentUpdate> = {};
  editSlug = '';
  editSortOrder = 0;
  editIsVisible = true;

  readonly currentEdit = computed(() => {
    const lang = this.activeLang();
    return this.editContents[lang] ?? { title: '', subtitle: '', content: '' };
  });

  readonly availableLangs = ['en', 'ua'];

  ngOnInit(): void {
    this.loadPages();
  }

  private loadPages(): void {
    this.loading.set(true);
    this.api.adminListPages().subscribe({
      next: (pages) => {
        this.pages.set(pages);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  selectPage(id: string): void {
    this.selectedId.set(id);
    const page = this.pages().find((p) => p.id === id);
    if (!page) return;

    this.editSlug = page.slug;
    this.editSortOrder = page.sortOrder;
    this.editIsVisible = page.isVisible;
    this.editContents = {};
    for (const lang of this.availableLangs) {
      const c = page.contents[lang];
      this.editContents[lang] = c
        ? { title: c.title, subtitle: c.subtitle, content: c.content }
        : { title: '', subtitle: '', content: '' };
    }
    this.showPreview.set(false);
    this.message.set('');
  }

  updateField(lang: string, field: 'title' | 'subtitle' | 'content', value: string): void {
    if (!this.editContents[lang]) {
      this.editContents[lang] = { title: '', subtitle: '', content: '' };
    }
    this.editContents[lang][field] = value;
  }

  savePage(): void {
    const page = this.selectedPage();
    if (!page) return;

    this.saving.set(true);
    this.message.set('');

    this.api
      .updatePage(page.id, {
        slug: this.editSlug !== page.slug ? this.editSlug : undefined,
        sortOrder: this.editSortOrder,
        isVisible: this.editIsVisible,
        contents: this.editContents,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.message.set('Saved');
          this.loadPages();
          setTimeout(() => this.message.set(''), 2000);
        },
        error: (err) => {
          this.saving.set(false);
          this.message.set(err?.error?.detail ?? 'Failed to save.');
        },
      });
  }

  createPage(): void {
    if (!this.newSlug.trim()) return;

    this.saving.set(true);
    this.api
      .createPage({
        slug: this.newSlug.trim(),
        sortOrder: this.newSortOrder,
        contents: {},
      })
      .subscribe({
        next: (page) => {
          this.saving.set(false);
          this.showNewForm.set(false);
          this.newSlug = '';
          this.newSortOrder = 0;
          this.pages.update((list) => [...list, page]);
          this.selectPage(page.id);
          this.loadPages();
        },
        error: (err) => {
          this.saving.set(false);
          this.message.set(err?.error?.detail ?? 'Failed to create.');
        },
      });
  }

  toggleVisibility(page: RegulationPageOut): void {
    const next = !page.isVisible;
    this.api.updatePage(page.id, { isVisible: next }).subscribe({
      next: () => {
        this.pages.update((list) =>
          list.map((p) => (p.id === page.id ? { ...p, isVisible: next } : p)),
        );
        if (this.selectedId() === page.id) {
          this.editIsVisible = next;
        }
      },
    });
  }

  async deletePage(page: RegulationPageOut): Promise<void> {
    const slug = page.slug;
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('admin.deleteRegulationConfirm', { slug }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;

    this.api.deletePage(page.id).subscribe({
      next: () => {
        if (this.selectedId() === page.id) {
          this.selectedId.set(null);
        }
        this.loadPages();
      },
    });
  }
}
