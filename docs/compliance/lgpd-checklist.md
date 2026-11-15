# LGPD Checklist — OpenOju

> Template técnico. Não substitui parecer jurídico. Ajuste ao contexto do
> deployer antes de publicar.

## Governança

- [ ] Encarregado (DPO) nomeado e contato público.
- [ ] Inventário de tratamentos (ROPA) atualizado.
- [ ] Base legal registrada: legítimo interesse para segurança patrimonial.
- [ ] LIA (Legitimate Interest Assessment) assinada.
- [ ] RIPD elaborado quando houver escala, risco elevado ou novas finalidades.
- [ ] Política de privacidade publicada e versionada.
- [ ] Termos de uso publicados.
- [ ] Aviso de câmera afixado nos locais filmados.
- [ ] Contratos com operadores e subprocessadores (DPA).
- [ ] Lista de subprocessadores pública.

## Princípios e finalidade

- [ ] Finalidade específica documentada por organização.
- [ ] Minimização: gravação apenas de áreas necessárias.
- [ ] Sem reconhecimento facial, biometria ou áudio por padrão.
- [ ] Acesso restrito a quem precisa operar/revisar.
- [ ] Segregação por organização validada por testes.

## Direitos do titular

- [ ] Formulário público por organização disponível.
- [ ] Fluxo de verificação de identidade definido.
- [ ] Prazo de resposta de 15 dias acompanhado.
- [ ] Exportação e exclusão implementadas com redação de terceiros.
- [ ] Legal hold pode suspender exclusão com justificativa registrada.
- [ ] Todas as ações auditadas.

## Retenção e descarte

- [ ] Retenção de mídia configurada (padrão 30 dias).
- [ ] Metadados de eventos: 12 meses.
- [ ] Access logs: 6 meses.
- [ ] Audit logs: 12 meses.
- [ ] Sessões: 30 dias.
- [ ] Webhook deliveries: 30 dias.
- [ ] Rotina automática de expurgo monitorada.
- [ ] Evidência de descarte registrada.

## Segurança

- [ ] TLS em trânsito.
- [ ] Criptografia em repouso avaliada; LUKS/SSE documentado como pendência.
- [ ] Segredos fora do código, `.env` com permissão 600.
- [ ] Backup testado e protegido.
- [ ] Controle de acesso por grupos locais.
- [ ] Logs de acesso e auditoria protegidos contra alteração.
- [ ] Plano de resposta a incidentes revisado.

## Terceiros

- [ ] Cloudflare, provedor OIDC, e-mail e webhooks mapeados.
- [ ] Transferência internacional avaliada.
- [ ] DPA assinado com cada operador.
- [ ] Avaliação de segurança de subprocessadores registrada.

## Incidentes

- [ ] Runbook publicado.
- [ ] Comunicação à ANPD em até 3 dias úteis.
- [ ] Comunicação a titulares quando houver risco relevante.
- [ ] Registro de incidentes mantido.
