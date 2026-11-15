# Marca OpenOju

Identidade, assets e regras de uso da marca.

## Nome

**OpenOju** — `Open` (open-source, olho aberto) + `Ojú`, palavra iorubá para
**olhos, face, aquilo que observa**. O nome não é o nome de um orixá e não
representa práticas religiosas.

| Contexto | Forma |
|---|---|
| Produto, UI, títulos | `OpenOju` |
| Slug, pacote, imagem, path | `openoju` |
| Variáveis de ambiente | `OJU_` |
| Containers | `openoju-api`, `openoju-worker`, `openoju-dispatcher`, `openoju-maintenance` |

Repositório: `github.com/pedromdev/openoju`.
Imagem: `ghcr.io/pedromdev/openoju`.

## Taglines

- PT-BR: **Olhos abertos para o que a câmera viu.**
- EN: **Open eyes on what the camera saw.**

Descrição curta:

> Self-hosted, open-source review of motion events from security cameras.
> Multi-tenant, SSO, API keys, S3 storage and LGPD-ready audit.

## Limites culturais

- Não usar imagens rituais, colares, ferramentas de orixás ou símbolos sagrados.
- Não associar o produto a proteção espiritual ou metáforas religiosas.
- Manter o símbolo abstrato: lente geométrica, sem cílios ou íris detalhada.
- Em materiais públicos, incluir a nota:

> **Sobre o nome** — *Ojú* é uma palavra iorubá para “olhos” ou “face”. O nome é
> uma referência cultural à ideia de observação atenta, não uma referência a
> orixás ou a práticas religiosas.

## Paleta

| Token | Hex | Uso |
|---|---|---|
| Ink | `#0B1220` | fundo principal, fundo do ícone |
| Slate | `#1E293B` | superfícies, bordas |
| Emerald | `#34D399` | cor primária, anel da lente |
| Amber | `#FBBF24` | evento detectado |
| Mist | `#E2E8F0` | texto principal |
| Emerald deep | `#059669` | emerald sobre fundo claro |
| Amber deep | `#B45309` | amber sobre fundo claro |

Emerald e amber são acentos. Erros usam rose; amber é reservado para eventos.

## Símbolo

Anel de lente com abertura e ponto amber:

- anel: raio 15, espessura 6, `#34D399`;
- abertura: 84° no canto superior direito;
- ponto: raio 4, `#FBBF24`.

Variantes:

| Arquivo | Uso |
|---|---|
| `logo-app.svg` | favicon, PWA, avatar |
| `logo-mark.svg` | header e docs em fundo escuro |
| `logo-mark-light.svg` | fundo claro |
| `logo-lockup.svg` | lockup horizontal em fundo escuro |
| `logo-lockup-card.svg` | README e GitHub (fundo navy próprio) |
| `logo-lockup-stacked.svg` | social preview e materiais quadrados |
| `mask-icon.svg` | Safari pinned tab |

## Assets

| Arquivo | Tamanho | Destino |
|---|---:|---|
| `favicon.ico` | 16/32/48 | `frontend/public/` |
| `favicon-16x16.png` | 16 | `frontend/public/` |
| `favicon-32x32.png` | 32 | `frontend/public/` |
| `apple-touch-icon.png` | 180 | `frontend/public/` |
| `icon-192.png` | 192 | `frontend/public/` |
| `icon-512.png` | 512 | `frontend/public/` |
| `icon-maskable-512.png` | 512 | `frontend/public/` |
| `mask-icon.svg` | 64 | `frontend/public/` |
| `og-image.png` | 1200×630 | `frontend/public/` |
| `manifest.webmanifest` | — | `frontend/public/` |
| `social-preview.png` | 1280×640 | `docs/assets/brand/` |
| `logo-*.svg` e `logo-*.png` | vários | `docs/assets/brand/` |

## Regenerar

Os assets são derivados dos SVGs em `docs/assets/brand/`:

```bash
./scripts/brand-assets.sh
```

Requisitos: ImageMagick 6 (`convert`) e a fonte Inter instalada.

## Usos proibidos

- Rotacionar, distorcer ou aplicar gradiente no símbolo.
- Trocar o emerald ou o amber por outras cores.
- Adicionar sombra, contorno ou efeito 3D.
- Usar ícones de biblioteca ou emoji como substituto do símbolo.
- Recriar o wordmark com outra fonte.

## Marca registrada

“Ojú” é uma palavra comum em iorubá; a distintividade vem do conjunto
**OpenOju + símbolo**. Recomenda-se registrar a marca composta e fazer busca
formal no INPI antes de investir em materiais de lançamento.
