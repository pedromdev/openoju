import { Injectable, computed, signal } from '@angular/core';

type Lang = 'pt-BR' | 'en';

const MESSAGES: Record<Lang, Record<string, string>> = {
  'pt-BR': {
    'nav.videos': 'Vídeos',
    'nav.profiles': 'Perfis',
    'nav.admin': 'Administração',
    'nav.logout': 'Sair',
    'nav.organization': 'Organização',
    'auth.login': 'Entrar',
    'auth.email': 'E-mail',
    'auth.password': 'Senha',
    'auth.sso': 'Entrar com SSO',
    'auth.setup': 'Configuração inicial',
    'auth.setupToken': 'Token de setup',
    'auth.orgName': 'Nome da organização',
    'auth.orgSlug': 'Slug (opcional)',
    'auth.displayName': 'Nome de exibição',
    'auth.invite': 'Aceitar convite',
    'auth.createAccount': 'Criar conta',
    'admin.members': 'Membros',
    'admin.groups': 'Grupos',
    'admin.apiKeys': 'API keys',
    'admin.webhooks': 'Webhooks',
    'admin.privacy': 'Privacidade',
    'admin.dsr': 'Solicitações (DSR)',
    'admin.audit': 'Auditoria',
    'common.save': 'Salvar',
    'common.create': 'Criar',
    'common.cancel': 'Cancelar',
    'common.delete': 'Excluir',
    'common.loading': 'Carregando…',
    'common.error': 'Ocorreu um erro.',
  },
  en: {
    'nav.videos': 'Videos',
    'nav.profiles': 'Profiles',
    'nav.admin': 'Administration',
    'nav.logout': 'Sign out',
    'nav.organization': 'Organization',
    'auth.login': 'Sign in',
    'auth.email': 'E-mail',
    'auth.password': 'Password',
    'auth.sso': 'Sign in with SSO',
    'auth.setup': 'Initial setup',
    'auth.setupToken': 'Setup token',
    'auth.orgName': 'Organization name',
    'auth.orgSlug': 'Slug (optional)',
    'auth.displayName': 'Display name',
    'auth.invite': 'Accept invitation',
    'auth.createAccount': 'Create account',
    'admin.members': 'Members',
    'admin.groups': 'Groups',
    'admin.apiKeys': 'API keys',
    'admin.webhooks': 'Webhooks',
    'admin.privacy': 'Privacy',
    'admin.dsr': 'Data subject requests',
    'admin.audit': 'Audit',
    'common.save': 'Save',
    'common.create': 'Create',
    'common.cancel': 'Cancel',
    'common.delete': 'Delete',
    'common.loading': 'Loading…',
    'common.error': 'Something went wrong.',
  },
};

@Injectable({ providedIn: 'root' })
export class I18nService {
  readonly lang = signal<Lang>(
    (localStorage.getItem('camera_lang') as Lang) === 'en' ? 'en' : 'pt-BR',
  );
  readonly label = computed(() => (this.lang() === 'en' ? 'EN' : 'PT'));

  t(key: string): string {
    return MESSAGES[this.lang()][key] ?? MESSAGES['pt-BR'][key] ?? key;
  }

  toggle(): void {
    const next: Lang = this.lang() === 'en' ? 'pt-BR' : 'en';
    this.lang.set(next);
    localStorage.setItem('camera_lang', next);
  }
}
