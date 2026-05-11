import { DatePipe } from '@angular/common';
import { Component, ElementRef, HostListener, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { BadgeComponent, BadgeVariant } from '../../../components/badge/badge.component';
import { BtnComponent } from '../../../components/btn/btn.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SelectDirective } from '../../../directives/select.directive';
import { AuthUser, ROLES, Role } from '../../../services/auth.service';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import { Community } from '../../../services/calendar-api.service';

const ROLE_BADGE_VARIANT: Record<Role, BadgeVariant> = {
  [ROLES.SUPER_ADMIN]: 'role-super-admin',
  [ROLES.ADMIN]: 'role-admin',
  [ROLES.COMMUNITY_MANAGER]: 'role-community-manager',
  [ROLES.MODERATOR]: 'role-moderator',
  [ROLES.JUDGE]: 'role-judge',
  [ROLES.DRIVER]: 'role-driver',
};

@Component({
  selector: 'app-user-item',
  imports: [DatePipe, FormsModule, TranslocoPipe, BadgeComponent, BtnComponent, FormFieldComponent, SelectDirective],
  templateUrl: './user-item.component.html',
  styleUrl: './user-item.component.scss',
})
export class UserItemComponent {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly user = input.required<AuthUser>();
  readonly editing = input(false);
  readonly canEdit = input(false);
  readonly availableRoles = input<Role[]>([]);
  readonly communities = input<Community[]>([]);

  readonly toggleEdit = output<void>();
  readonly changeRole = output<Role>();
  readonly assignCommunity = output<string>();
  readonly toggleBlock = output<void>();
  readonly forceLogout = output<void>();

  readonly menuOpen = signal(false);

  readonly roleVariant = computed<BadgeVariant>(() => ROLE_BADGE_VARIANT[this.user().role]);
  readonly assignedCommunityId = computed(() => this.user().managedCommunityIds?.[0] ?? '');
  readonly assignedCommunityName = computed(() => {
    const id = this.assignedCommunityId();
    if (!id) return '';
    return this.communities().find((c) => c.id === id)?.name ?? '';
  });
  readonly canBlock = computed(() => this.canEdit() && this.user().role !== ROLES.SUPER_ADMIN);
  readonly fallbackInitial = computed(() => this.user().displayName.charAt(0).toUpperCase() || '?');
  readonly roleLabel = computed(() => this.user().role.replace('_', ' '));

  formatRole(role: Role): string {
    return role.replace('_', ' ');
  }

  onToggleEdit(): void {
    this.menuOpen.set(false);
    this.toggleEdit.emit();
  }

  onRoleChange(role: Role): void {
    this.changeRole.emit(role);
  }

  onCommunityChange(id: string): void {
    this.assignCommunity.emit(id);
  }

  toggleMenu(): void {
    this.menuOpen.update((v) => !v);
  }

  async onToggleBlock(): Promise<void> {
    this.menuOpen.set(false);
    const u = this.user();
    const message = u.blocked
      ? this.transloco.translate('admin.confirmUnblock', { name: u.displayName })
      : this.transloco.translate('admin.confirmBlock', { name: u.displayName });
    const ok = await this.confirmSvc.confirm({
      message,
      confirmLabel: this.transloco.translate(u.blocked ? 'admin.unblock' : 'admin.block'),
      danger: !u.blocked,
    });
    if (!ok) return;
    this.toggleBlock.emit();
  }

  async onForceLogout(): Promise<void> {
    this.menuOpen.set(false);
    const ok = await this.confirmSvc.confirm({
      message: this.transloco.translate('admin.confirmForceLogout', { name: this.user().displayName }),
      confirmLabel: this.transloco.translate('admin.forceLogout'),
      danger: true,
    });
    if (!ok) return;
    this.forceLogout.emit();
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.menuOpen()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.menuOpen.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.menuOpen()) this.menuOpen.set(false);
  }
}
