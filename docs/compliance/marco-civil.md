# Marco Civil da Internet — Requisitos de Logs

Referência: Lei 12.965/2014, arts. 10, 13, 15 e 22 a 24.

## Escopo

A aplicação registra logs de acesso a recursos e ações administrativas para
segurança, auditoria e cumprimento de obrigações legais. Este documento cobre
o deployer self-hosted.

## Access logs (6 meses)

Registrar, no mínimo:

- data e hora (UTC);
- organização;
- usuário ou API key;
- ação (`view_video`, `stream`, `download_clip`, `export`, `delete`, ...);
- tipo e identificador do recurso;
- endereço IP de origem;
- user agent;
- resultado (sucesso/negado).

Regras:

- retenção mínima de 6 meses;
- armazenamento em ambiente controlado e com acesso restrito;
- proibição de uso para finalidade diversa sem base legal;
- logs não devem conter conteúdo de vídeo nem dados sensíveis desnecessários;
- descarte automatizado após o prazo, salvo obrigação legal ou legal hold.

## Audit logs (12 meses)

Ações administrativas (membros, grupos, API keys, webhooks, privacidade,
configurações) geram trilha de auditoria imutável por 12 meses, com ator,
recurso, metadados e IP.

## Transparência

- Política de privacidade deve descrever os logs coletados.
- Pedidos do titular sobre logs devem ser atendidos nos limites da lei.
- Ordem judicial de fornecimento deve passar por revisão jurídica.

## Segurança dos logs

- Acesso por menor privilégio.
- Backup protegido.
- Relógio sincronizado (NTP).
- Monitoramento de falha de gravação.

## Pendências conhecidas

- Retenção configurável por organização.
- Exportação assinada de logs para auditoria externa.
