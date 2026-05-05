import { Component, inject, OnInit, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { EmptyComponent } from '../../../components/empty/empty.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { InputDirective } from '../../../directives/input.directive';
import { MarkdownPipe } from '../../../pipes/markdown.pipe';
import {
  RegulationApiService,
  RegulationContentUpdate,
  RegulationPageOut,
} from '../../../services/regulation-api.service';

@Component({
  selector: 'app-admin-regulations-tab',
  standalone: true,
  imports: [FormsModule, BtnComponent, CardComponent, EmptyComponent, FormFieldComponent, SpinnerComponent, InputDirective, MarkdownPipe],
  templateUrl: './admin-regulations-tab.component.html',
  styleUrl: './admin-regulations-tab.component.scss',
})
export class AdminRegulationsTabComponent implements OnInit {
  private readonly api = inject(RegulationApiService);

  readonly pages = signal<RegulationPageOut[]>([]);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly message = signal('');
  readonly selectedSlug = signal<string | null>(null);
  readonly activeLang = signal('en');
  readonly showPreview = signal(false);

  // New page form
  readonly showNewForm = signal(false);
  newSlug = '';
  newSortOrder = 0;

  readonly selectedPage = computed(() => {
    const slug = this.selectedSlug();
    return this.pages().find((p) => p.slug === slug) ?? null;
  });

  // Edit buffer: Record<lang, { title, subtitle, content }>
  editContents: Record<string, RegulationContentUpdate> = {};
  editSlug = '';
  editSortOrder = 0;

  readonly currentEdit = computed(() => {
    const lang = this.activeLang();
    return this.editContents[lang] ?? { title: '', subtitle: '', content: '' };
  });

  readonly availableLangs = ['en', 'uk'];

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

  selectPage(slug: string): void {
    this.selectedSlug.set(slug);
    const page = this.pages().find((p) => p.slug === slug);
    if (!page) return;

    this.editSlug = page.slug;
    this.editSortOrder = page.sortOrder;
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
    const slug = this.selectedSlug();
    if (!slug) return;

    this.saving.set(true);
    this.message.set('');

    this.api.updatePage(slug, {
      slug: this.editSlug !== slug ? this.editSlug : undefined,
      sort_order: this.editSortOrder,
      contents: this.editContents,
    }).subscribe({
      next: () => {
        this.saving.set(false);
        this.message.set('Saved');
        if (this.editSlug !== slug) {
          this.selectedSlug.set(this.editSlug);
        }
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
    this.api.createPage({
      slug: this.newSlug.trim(),
      sort_order: this.newSortOrder,
      contents: {},
    }).subscribe({
      next: (page) => {
        this.saving.set(false);
        this.showNewForm.set(false);
        this.newSlug = '';
        this.newSortOrder = 0;
        this.loadPages();
        this.selectPage(page.slug);
      },
      error: (err) => {
        this.saving.set(false);
        this.message.set(err?.error?.detail ?? 'Failed to create.');
      },
    });
  }

  deletePage(slug: string): void {
    if (!window.confirm(`Delete regulation page "${slug}"?`)) return;

    this.api.deletePage(slug).subscribe({
      next: () => {
        if (this.selectedSlug() === slug) {
          this.selectedSlug.set(null);
        }
        this.loadPages();
      },
    });
  }
}
