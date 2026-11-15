import { JsonPipe, NgClass } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import {
  API_KEY_SCOPES,
  ApiKey,
  AuditLog,
  DataSubjectRequest,
  Member,
  PERMISSIONS,
  PermissionGroup,
  PrivacySettings,
  WEBHOOK_EVENTS,
  WebhookDelivery,
  WebhookEndpoint,
} from '../../core/models';

type Tab =
  | 'members'
  | 'groups'
  | 'apiKeys'
  | 'webhooks'
  | 'privacy'
  | 'dsr'
  | 'audit';

@Component({
  selector: 'app-admin-page',
  imports: [FormsModule, NgClass, JsonPipe],
  templateUrl: './admin-page.html',
  styles: [
    `
      .input {
        width: 100%;
        border-radius: 0.75rem;
        border: 1px solid rgb(51 65 85);
        background: rgb(2 6 23);
        padding: 0.5rem 0.75rem;
        color: rgb(241 245 249);
        outline: none;
      }
      .input:focus {
        border-color: rgb(16 185 129);
      }
      .btn {
        border-radius: 0.75rem;
        background: rgb(16 185 129);
        padding: 0.5rem 1rem;
        font-weight: 500;
        color: rgb(2 6 23);
      }
    `,
  ],
})
export class AdminPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly auth = inject(AuthService);
  readonly i18n = inject(I18nService);

  readonly tab = signal<Tab>('members');
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);

  readonly members = signal<Member[]>([]);
  readonly groups = signal<PermissionGroup[]>([]);
  readonly apiKeys = signal<ApiKey[]>([]);
  readonly webhooks = signal<WebhookEndpoint[]>([]);
  readonly dsr = signal<DataSubjectRequest[]>([]);
  readonly audit = signal<AuditLog[]>([]);
  readonly privacy = signal<PrivacySettings | null>(null);
  readonly deliveries = signal<Record<string, WebhookDelivery[]>>({});

  readonly tabs: { key: Tab; label: string }[] = [
    { key: 'members', label: 'admin.members' },
    { key: 'groups', label: 'admin.groups' },
    { key: 'apiKeys', label: 'admin.apiKeys' },
    { key: 'webhooks', label: 'admin.webhooks' },
    { key: 'privacy', label: 'admin.privacy' },
    { key: 'dsr', label: 'admin.dsr' },
    { key: 'audit', label: 'admin.audit' },
  ];
  readonly dsrStatuses = ['new', 'verified', 'in_progress', 'completed', 'rejected'];
  readonly permissions = PERMISSIONS;
  readonly scopes = API_KEY_SCOPES;
  readonly webhookEvents = WEBHOOK_EVENTS;

  inviteEmail = '';
  inviteGroupId = '';
  inviteToken = '';

  groupId: string | null = null;
  groupName = '';
  groupDescription = '';
  groupPermissions: string[] = [];

  apiKeyName = '';
  apiKeyScopes: string[] = ['ingest:write'];
  newApiKey = '';

  webhookName = '';
  webhookUrl = '';
  webhookEventsSelected: string[] = ['event.created'];
  newWebhookSecret = '';

  privacyForm = {
    legal_basis: 'legitimate_interest',
    retention_media_days: 30,
    retention_event_months: 12,
    retention_access_logs_months: 6,
    retention_audit_months: 12,
    dpo_name: '',
    dpo_email: '',
    privacy_policy_version: '',
    privacy_policy_url: '',
    camera_notice_text: '',
  };
  retentionResult: Record<string, number> | null = null;

  ngOnInit(): void {
    this.loadMembers();
    this.loadGroups();
  }

  setTab(tab: Tab): void {
    this.tab.set(tab);
    if (tab === 'members') this.loadMembers();
    if (tab === 'groups') this.loadGroups();
    if (tab === 'apiKeys') this.loadApiKeys();
    if (tab === 'webhooks') this.loadWebhooks();
    if (tab === 'privacy') this.loadPrivacy();
    if (tab === 'dsr') this.loadDsr();
    if (tab === 'audit') this.loadAudit();
  }

  can(permission: string): boolean {
    return this.auth.has(permission);
  }

  groupNames(member: Member): string {
    return member.groups.map((group) => group.name).join(', ') || '—';
  }

  private fail(err: unknown, fallback: string): void {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    this.error.set(typeof detail === 'string' ? detail : fallback);
  }

  private ok(message: string): void {
    this.notice.set(message);
    setTimeout(() => this.notice.set(null), 4000);
  }

  loadMembers(): void {
    this.api.listMembers().subscribe({
      next: (members) => this.members.set(members),
      error: (err) => this.fail(err, 'Falha ao carregar membros.'),
    });
  }

  invite(): void {
    this.error.set(null);
    this.inviteToken = '';
    this.api.inviteMember(this.inviteEmail, this.inviteGroupId ? [this.inviteGroupId] : []).subscribe({
      next: (result) => {
        this.inviteToken = result.token;
        this.inviteEmail = '';
        this.ok('Convite criado. Copie o token abaixo e envie ao membro.');
        this.loadMembers();
        this.loadGroups();
      },
      error: (err) => this.fail(err, 'Falha ao convidar.'),
    });
  }

  setMemberStatus(member: Member, status: string): void {
    this.api.updateMember(member.id, status).subscribe({
      next: () => this.loadMembers(),
      error: (err) => this.fail(err, 'Falha ao atualizar membro.'),
    });
  }

  loadGroups(): void {
    this.api.listGroups().subscribe({
      next: (groups) => this.groups.set(groups),
      error: (err) => this.fail(err, 'Falha ao carregar grupos.'),
    });
  }

  editGroup(group: PermissionGroup): void {
    this.groupId = group.id;
    this.groupName = group.name;
    this.groupDescription = group.description;
    this.groupPermissions = [...group.permissions];
  }

  resetGroup(): void {
    this.groupId = null;
    this.groupName = '';
    this.groupDescription = '';
    this.groupPermissions = [];
  }

  toggleGroupPermission(permission: string): void {
    this.groupPermissions = this.groupPermissions.includes(permission)
      ? this.groupPermissions.filter((item) => item !== permission)
      : [...this.groupPermissions, permission];
  }

  saveGroup(): void {
    const payload = {
      name: this.groupName,
      description: this.groupDescription,
      permissions: this.groupPermissions,
    };
    const request = this.groupId
      ? this.api.updateGroup(this.groupId, payload)
      : this.api.createGroup(payload);
    request.subscribe({
      next: () => {
        this.resetGroup();
        this.loadGroups();
        this.ok('Grupo salvo.');
      },
      error: (err) => this.fail(err, 'Falha ao salvar grupo.'),
    });
  }

  loadApiKeys(): void {
    this.api.listApiKeys().subscribe({
      next: (keys) => this.apiKeys.set(keys),
      error: (err) => this.fail(err, 'Falha ao carregar API keys.'),
    });
  }

  toggleScope(scope: string): void {
    this.apiKeyScopes = this.apiKeyScopes.includes(scope)
      ? this.apiKeyScopes.filter((item) => item !== scope)
      : [...this.apiKeyScopes, scope];
  }

  createApiKey(): void {
    this.newApiKey = '';
    this.api.createApiKey(this.apiKeyName, this.apiKeyScopes).subscribe({
      next: (result) => {
        this.newApiKey = result.key;
        this.apiKeyName = '';
        this.loadApiKeys();
        this.ok('API key criada. O segredo aparece apenas uma vez.');
      },
      error: (err) => this.fail(err, 'Falha ao criar API key.'),
    });
  }

  revokeApiKey(key: ApiKey): void {
    if (!confirm(`Revogar a API key ${key.name}?`)) return;
    this.api.revokeApiKey(key.id).subscribe({
      next: () => this.loadApiKeys(),
      error: (err) => this.fail(err, 'Falha ao revogar API key.'),
    });
  }

  loadWebhooks(): void {
    this.api.listWebhooks().subscribe({
      next: (endpoints) => this.webhooks.set(endpoints),
      error: (err) => this.fail(err, 'Falha ao carregar webhooks.'),
    });
  }

  toggleWebhookEvent(event: string): void {
    this.webhookEventsSelected = this.webhookEventsSelected.includes(event)
      ? this.webhookEventsSelected.filter((item) => item !== event)
      : [...this.webhookEventsSelected, event];
  }

  createWebhook(): void {
    this.newWebhookSecret = '';
    this.api
      .createWebhook({
        name: this.webhookName,
        url: this.webhookUrl,
        events: this.webhookEventsSelected,
        active: true,
      })
      .subscribe({
        next: (result) => {
          this.newWebhookSecret = result.secret;
          this.webhookName = '';
          this.webhookUrl = '';
          this.loadWebhooks();
          this.ok('Webhook criado. Guarde o segredo para validar assinaturas.');
        },
        error: (err) => this.fail(err, 'Falha ao criar webhook.'),
      });
  }

  testWebhook(endpoint: WebhookEndpoint): void {
    this.api.testWebhook(endpoint.id).subscribe({
      next: (result) => {
        this.ok(
          `Teste: ${result.delivery.status} (HTTP ${result.delivery.response_status ?? '—'})`,
        );
        this.loadDeliveries(endpoint);
      },
      error: (err) => this.fail(err, 'Falha ao testar webhook.'),
    });
  }

  loadDeliveries(endpoint: WebhookEndpoint): void {
    this.api.webhookDeliveries(endpoint.id).subscribe({
      next: (items) =>
        this.deliveries.update((current) => ({ ...current, [endpoint.id]: items })),
      error: (err) => this.fail(err, 'Falha ao carregar entregas.'),
    });
  }

  retryDelivery(endpoint: WebhookEndpoint, delivery: WebhookDelivery): void {
    this.api.retryWebhookDelivery(endpoint.id, delivery.id).subscribe({
      next: () => this.loadDeliveries(endpoint),
      error: (err) => this.fail(err, 'Falha ao reenviar entrega.'),
    });
  }

  deleteWebhook(endpoint: WebhookEndpoint): void {
    if (!confirm(`Excluir o webhook ${endpoint.name}?`)) return;
    this.api.deleteWebhook(endpoint.id).subscribe({
      next: () => this.loadWebhooks(),
      error: (err) => this.fail(err, 'Falha ao excluir webhook.'),
    });
  }

  loadPrivacy(): void {
    this.api.getPrivacy().subscribe({
      next: (privacy) => {
        this.privacy.set(privacy);
        this.privacyForm = {
          legal_basis: privacy.legal_basis,
          retention_media_days: privacy.retention_media_days,
          retention_event_months: privacy.retention_event_months,
          retention_access_logs_months: privacy.retention_access_logs_months,
          retention_audit_months: privacy.retention_audit_months,
          dpo_name: privacy.dpo_name ?? '',
          dpo_email: privacy.dpo_email ?? '',
          privacy_policy_version: privacy.privacy_policy_version ?? '',
          privacy_policy_url: privacy.privacy_policy_url ?? '',
          camera_notice_text: privacy.camera_notice_text ?? '',
        };
      },
      error: (err) => this.fail(err, 'Falha ao carregar privacidade.'),
    });
  }

  savePrivacy(): void {
    this.api
      .updatePrivacy({
        ...this.privacyForm,
        dpo_name: this.privacyForm.dpo_name || null,
        dpo_email: this.privacyForm.dpo_email || null,
        privacy_policy_version: this.privacyForm.privacy_policy_version || null,
        privacy_policy_url: this.privacyForm.privacy_policy_url || null,
        camera_notice_text: this.privacyForm.camera_notice_text || null,
      })
      .subscribe({
        next: () => this.ok('Configurações de privacidade salvas.'),
        error: (err) => this.fail(err, 'Falha ao salvar privacidade.'),
      });
  }

  runRetention(): void {
    this.api.updatePrivacy({ ...this.privacyForm }).subscribe({
      error: () => undefined,
    });
    this.api.runRetention().subscribe({
      next: (counts) => {
        this.retentionResult = counts;
        this.ok('Retenção executada.');
      },
      error: (err) => this.fail(err, 'Falha ao executar retenção.'),
    });
  }

  loadDsr(): void {
    this.api.listDsr().subscribe({
      next: (rows) => this.dsr.set(rows),
      error: (err) => this.fail(err, 'Falha ao carregar solicitações.'),
    });
  }

  setDsrStatus(request: DataSubjectRequest, status: string): void {
    this.api.updateDsr(request.id, status).subscribe({
      next: () => this.loadDsr(),
      error: (err) => this.fail(err, 'Falha ao atualizar solicitação.'),
    });
  }

  exportDsr(request: DataSubjectRequest): void {
    this.api.exportDsr(request.id).subscribe({
      next: (payload) => {
        const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: 'application/json',
        });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${request.protocol}.json`;
        anchor.click();
        URL.revokeObjectURL(url);
      },
      error: (err) => this.fail(err, 'Falha ao exportar.'),
    });
  }

  executeDeletion(request: DataSubjectRequest): void {
    if (!confirm('Excluir mídia dos eventos correspondentes? Legal holds serão respeitados.')) {
      return;
    }
    this.api.executeDsrDeletion(request.id).subscribe({
      next: (result) =>
        this.ok(
          `${result.deleted_events} evento(s) excluído(s); ${result.skipped_legal_hold} sob legal hold.`,
        ),
      error: (err) => this.fail(err, 'Falha ao excluir mídia.'),
    });
  }

  loadAudit(): void {
    this.api.listAudit().subscribe({
      next: (logs) => this.audit.set(logs),
      error: (err) => this.fail(err, 'Falha ao carregar auditoria.'),
    });
  }

  date(value: string | null): string {
    return value ? new Date(value).toLocaleString() : '—';
  }
}
