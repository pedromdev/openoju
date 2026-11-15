# Subprocessadores

> Lista pública de subprocessadores por deployer. Atualize ao contratar ou
> remover serviços.

| Subprocessador | Finalidade | Dados tratados | Localização | DPA | Observações |
|---|---|---|---|---|---|
| Cloudflare | CDN, TLS e tunnel | tráfego HTTP, IP | Global | Sim | Não armazena vídeo por padrão |
| Provedor de hospedagem | VMs, armazenamento e rede | todos os dados | Definir | Sim | Inclui Postgres e MinIO |
| Provedor OIDC | Autenticação SSO | e-mail, nome, subject | Definir | Sim | Roles do IdP não são usadas |
| Serviço de e-mail | Convites e notificações | e-mail, nome | Definir | Sim | Opcional |
| Destino de webhook | Notificação de eventos | metadados de evento | Definir | Sim | Configurado por organização |

## Regras

1. Nenhum subprocessador pode receber mais dados do que o necessário.
2. Novos subprocessadores exigem avaliação de segurança e atualização desta
   lista.
3. Transferência internacional deve ser avaliada e documentada.
4. Contratos devem prever notificação de incidentes e direito de auditoria.

## Histórico de alterações

| Data | Alteração |
|---|---|
| 2026-11-14 | Lista inicial criada |
