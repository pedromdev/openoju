# ROPA — Registro de Operações de Tratamento

> Template. Preencha uma linha por operação de tratamento.

| Campo | Conteúdo |
|---|---|
| Organização / controladora | |
| Operador / deployer | |
| Nome do tratamento | Monitoramento por câmeras de segurança |
| Finalidade | Segurança patrimonial e proteção de pessoas e bens |
| Base legal | Legítimo interesse (LGPD art. 7º, IX) |
| Categorias de titulares | Funcionários, visitantes, terceiros, transeuntes |
| Categorias de dados | Imagem em vídeo, horário, local, metadados de movimento |
| Dados sensíveis | Não intencionais; não há biometria ou reconhecimento facial |
| Origem | Câmeras IP / arquivos DAV enviados por operadores |
| Operadores/subprocessadores | Cloudflare, provedor OIDC, MinIO/S3, e-mail, webhooks |
| Transferência internacional | Avaliar conforme provedor |
| Retenção | Mídia 30 dias; metadados 12 meses; logs conforme política |
| Medidas de segurança | TLS, RBAC, isolamento por organização, audit/access logs, backup |
| Direitos do titular | Formulário público; prazo de 15 dias |
| Avaliação de impacto | RIPD quando em escala ou risco elevado |
| Responsável | DPO/enccarregado |
| Última revisão | |

## Observações

- LUKS/criptografia em repouso está adiada; registrar no risk register.
- A aplicação é operadora interna quando usada pela própria empresa.
- Em oferta a terceiros, cada organização é controladora e o deployer é
  operador; DPA é obrigatório.
