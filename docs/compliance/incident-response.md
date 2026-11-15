# Resposta a Incidentes de Segurança e Privacidade

## Objetivo

Detectar, conter, erradicar, recuperar e comunicar incidentes que afetem
confidencialidade, integridade ou disponibilidade de dados pessoais.

## Classificação

| Severidade | Exemplo | Prazo de triagem |
|---|---|---:|
| Crítica | Vazamento cross-tenant confirmado, acesso administrativo indevido | Imediata |
| Alta | Credencial exposta, webhook com SSRF, backup acessível | 1 hora |
| Média | Falha de retenção, log ausente, erro de permissão | 1 dia útil |
| Baixa | Tentativa de login bloqueada, ruído de scanner | 5 dias úteis |

## Fluxo

1. **Detectar** — alerta, relato ou auditoria.
2. **Registrar** — abrir incidente com data/hora UTC, relator, sistemas
   afetados, organizações e titulares potencialmente afetados.
3. **Conter** — revogar sessões/API keys, bloquear IP, desativar endpoint,
   rotacionar segredos.
4. **Avaliar risco** — natureza dos dados, volume, reversibilidade, risco de
   dano relevante.
5. **Erradicar** — corrigir causa raiz, aplicar patch e migration.
6. **Recuperar** — restaurar backup testado e validar integridade.
7. **Comunicar** — ANPD em até 3 dias úteis após o conhecimento; complemento
   em até 20 dias úteis; titulares quando houver risco relevante.
8. **Pós-incidente** — lições aprendidas, atualização de RIPD/ROPA e novos
   controles.

## Evidências

- Preservar logs e snapshots antes de qualquer limpeza.
- Registrar cadeia de custódia.
- Não registrar conteúdo de vídeo em tickets.
- Armazenar evidências em local com acesso restrito.

## Comunicação à ANPD

Modelo mínimo:

- controladora e encarregado;
- descrição do incidente;
- dados e titulares afetados;
- medidas técnicas e de segurança;
- riscos e mitigações;
- medidas de comunicação aos titulares.

## Contatos

- Encarregado (DPO):
- Responsável técnico:
- Jurídico:
- Infraestrutura:

## Testes

- Simulação anual de vazamento cross-tenant.
- Teste de restore de backup.
- Revisão de credenciais expostas.
