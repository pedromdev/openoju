# RIPD — Relatório de Impacto à Proteção de Dados

> Template. Elaborar antes de operar câmeras em escala ou em áreas sensíveis.

## 1. Identificação

- Controladora:
- Operadora/deployer:
- Encarregado (DPO):
- Data da avaliação:
- Versão:

## 2. Descrição do tratamento

- Captura de vídeo de áreas comuns/patrimoniais.
- Geração de eventos de movimentação, clipes e thumbnails.
- Revisão humana de eventos.
- Retenção e descarte automatizados.

## 3. Necessidade e proporcionalidade

- Áreas filmadas e finalidade de cada câmera.
- Alternativas menos invasivas consideradas.
- Medidas para evitar captura de áreas privadas.
- Máscaras de privacidade aplicadas no perfil da câmera.
- Ausência de áudio, biometria e reconhecimento facial por padrão.

## 4. Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Acesso indevido a vídeos | Média | Alto | RBAC, sessão segura, audit logs |
| Vazamento cross-tenant | Baixa | Alto | isolamento por org e testes |
| Retenção excessiva | Média | Médio | expurgo automático e legal hold |
| Captura de áreas privadas | Média | Alto | posicionamento e máscaras |
| Acesso por terceiros | Baixa | Alto | DPA, subprocessadores avaliados |
| Falta de criptografia em repouso | Média | Alto | LUKS/SSE documentado como pendência |

## 5. Medidas e salvaguardas

- TLS obrigatório.
- Sessão HttpOnly + CSRF; API keys com hash e escopo.
- Isolamento lógico por organização.
- Logs de acesso e auditoria.
- Backup protegido e restore testado.
- Treinamento de operadores.
- Aviso de câmera e política de privacidade publicados.

## 6. Consulta aos titulares

- Canal de atendimento:
- Formulário público:
- Prazo de resposta: 15 dias.

## 7. Conclusão

- Risco residual:
- Aprovação do DPO:
- Revisão prevista:
