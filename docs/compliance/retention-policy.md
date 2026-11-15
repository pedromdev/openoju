# Política de Retenção e Descarte

## Tabela de retenção

| Dado | Prazo padrão | Configurável | Observações |
|---|---:|---|---|
| Originais de vídeo | 30 dias | Sim, por organização | Base para reprocessamento |
| Proxies MP4 | 30 dias | Sim | Derivados do original |
| Clipes de eventos | 30 dias | Sim | Derivados do original |
| Thumbnails | 30 dias | Sim | Derivados do original |
| Metadados de eventos | 12 meses | Sim | Revisão e histórico |
| Access logs | 6 meses | Não abaixo de 6 meses | Marco Civil |
| Audit logs | 12 meses | Não abaixo de 12 meses | Ações administrativas |
| Sessões | 30 dias | Sim | Revogação antecipada permitida |
| Convites | 7 dias | Sim | Expiram automaticamente |
| Webhook deliveries | 30 dias | Sim | Diagnóstico |
| Upload sessions incompletas | 48 horas | Sim | Limpeza automática |

## Regras

1. Legal hold sobrepõe qualquer prazo e suspende o descarte.
2. Obrigação legal específica pode exigir retenção maior, com registro.
3. O expurgo roda diariamente e registra contagem por tipo.
4. Falhas de expurgo geram alerta operacional.
5. Dados descartados não podem ser recuperados de backups dentro do prazo de
   rotação definido pelo deployer.
6. Logs de descarte devem ser preservados sem conteúdo pessoal.

## Implementação

- Job de retenção dedicado.
- Consultas sempre filtradas por organização.
- Métricas: itens removidos, bytes liberados, erros.

## Pendências

- Definir retenção de backups por deployer.
- Implementar SSE/LUKS para mídia em repouso.
