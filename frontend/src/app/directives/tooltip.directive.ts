import {
  Directive,
  ElementRef,
  OnDestroy,
  Renderer2,
  booleanAttribute,
  inject,
  input,
} from '@angular/core';

/** Gap between the tooltip and the element it describes, and from the viewport edge. */
const OFFSET = 8;

let nextId = 0;

/**
 * Lightweight hover/focus tooltip. The element is appended to `document.body` and
 * positioned with `position: fixed`, so it escapes ancestors that clip their
 * overflow (the calendar month grid does). Styles live in `src/styles.scss` under
 * `.app-tooltip` — a component stylesheet cannot reach it outside the host tree.
 */
@Directive({
  selector: '[appTooltip]',
  host: {
    '(mouseenter)': 'show()',
    '(focusin)': 'show()',
    '(mouseleave)': 'hide()',
    '(focusout)': 'hide()',
  },
})
export class TooltipDirective implements OnDestroy {
  /** Text to show. `\n` separates lines — the tooltip renders with `white-space: pre-line`. */
  readonly appTooltip = input<string>('');

  /** Only show when the host's text is actually clipped, so short labels stay quiet. */
  readonly tooltipWhenTruncated = input(false, { transform: booleanAttribute });

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private readonly renderer = inject(Renderer2);
  private tip: HTMLElement | null = null;

  // Document-level listeners are bound only while a tooltip is open: a month
  // grid holds dozens of these directives and none of them need to listen idly.
  private teardown: (() => void)[] = [];

  ngOnDestroy(): void {
    this.hide();
  }

  show(): void {
    if (this.tip) return;

    const text = this.appTooltip().trim();
    if (!text) return;

    // Touch devices have no hover, and the calendar renders dots instead of
    // labels there anyway — tapping already opens the day drawer.
    if (typeof window.matchMedia === 'function' && !window.matchMedia('(hover: hover)').matches) {
      return;
    }

    if (this.tooltipWhenTruncated() && !this.isTruncated()) return;

    const tip = this.renderer.createElement('div') as HTMLElement;
    const id = `app-tooltip-${nextId++}`;
    this.renderer.setAttribute(tip, 'id', id);
    this.renderer.setAttribute(tip, 'role', 'tooltip');
    this.renderer.addClass(tip, 'app-tooltip');
    this.renderer.setProperty(tip, 'textContent', text);
    this.renderer.appendChild(document.body, tip);
    this.renderer.setAttribute(this.host, 'aria-describedby', id);

    this.tip = tip;
    this.position();

    const close = () => this.hide();
    this.teardown = [
      this.renderer.listen('window', 'scroll', close),
      this.renderer.listen('window', 'resize', close),
      this.renderer.listen('document', 'keydown.escape', close),
    ];
  }

  hide(): void {
    if (!this.tip) return;
    for (const off of this.teardown) off();
    this.teardown = [];
    this.renderer.removeChild(document.body, this.tip);
    this.renderer.removeAttribute(this.host, 'aria-describedby');
    this.tip = null;
  }

  /** The chip clips on its inner span, so measure that when there is one. */
  private isTruncated(): boolean {
    const target = (this.host.firstElementChild as HTMLElement | null) ?? this.host;
    return target.scrollWidth > target.clientWidth;
  }

  /** Above the host by default, flipped below when there is no room up there. */
  private position(): void {
    const tip = this.tip;
    if (!tip) return;

    const anchor = this.host.getBoundingClientRect();
    const size = tip.getBoundingClientRect();

    const top =
      anchor.top >= size.height + OFFSET
        ? anchor.top - size.height - OFFSET
        : anchor.bottom + OFFSET;

    const centred = anchor.left + anchor.width / 2 - size.width / 2;
    const left = Math.max(OFFSET, Math.min(centred, window.innerWidth - size.width - OFFSET));

    this.renderer.setStyle(tip, 'top', `${Math.round(top)}px`);
    this.renderer.setStyle(tip, 'left', `${Math.round(left)}px`);
    this.renderer.addClass(tip, 'app-tooltip--visible');
  }
}
