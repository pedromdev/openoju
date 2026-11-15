# Validação com DAV real e navegador

## Amostra

- Arquivo: `camera-2026-11-04-2130.dav`
- Tamanho: 226 MB
- Duração: 30 minutos
- Vídeo: H.264 High, 1280×720, 15 fps, yuv420p
- Container: `dhav` (FFmpeg reconheceu sem conversão)
- Áudio: nenhum

`ffprobe` retornou `format.start_time = 1793827800`, que corresponde ao horário
de parede do OSD: `2026-11-04 21:30:00`. O valor é tratado como relógio local da
câmera e propagado para os eventos como `start_wallclock`.

## Perfil e máscaras

Perfil `01 - Interfone externo`:

| Região | X | Y | Largura | Altura |
|---|---:|---:|---:|---:|
| Relógio/OSD superior direito | 72% | 2% | 26% | 7% |
| Nome da câmera inferior esquerdo | 0% | 90% | 30% | 10% |

As máscaras foram aplicadas no frame reduzido da análise. Sem elas, os dígitos do
relógio gerariam eventos a cada segundo. Com elas, a detecção ficou estável.

## Resultado da análise

- 26 eventos
- 08:05 de movimentação acumulada
- Primeiro evento: `21:30:58` (00:58 no vídeo)
- Eventos com duração entre 2 s e 1 min 46 s
- Thumbnails e clipes gerados para os eventos

## Testes de navegador

Feitos com Playwright, em uma instância local sem Basic Auth para evitar o
diálogo nativo do navegador. O fluxo público continua protegido.

- Lista de vídeos carregou os vídeos de teste e o DAV real.
- Detalhe do DAV abriu com player, timeline, resumo e 26 eventos.
- `Reproduzir` posicionou o player em `currentTime = 58`.
- `Confirmar` atualizou o evento para `Confirmado`.
- `Clipe` abriu o modal com o MP4 do trecho.
- Perfis exibiram as duas máscaras, a prévia sobre a imagem e os campos
  normalizados.
- Nenhum erro de console no fluxo local.
- Seleção múltipla de arquivos foi testada com dois MP4s e retornou o aviso
  “2 arquivos enviados”.

## Lote de amostras

O diretório de importação continha 8 DAVs. Todos foram importados pelo caminho,
usando o perfil `01 - Interfone externo`, e analisados. Total: 87 eventos na
primeira passagem.

Os vídeos sintéticos usados nos testes (`moving*.mp4`, `test1080p-hevc.mp4`,
`public-test.mp4`, `multi-test-*.mp4`) e a cópia do DAV de teste em `inbox` foram
removidos ao final. As fontes originais no diretório de importação foram
preservadas.

## Benchmark CPU x VAAPI com DAV real

Trecho de 5 minutos de um DAV de referência (1280×720, 15 fps, H.264):

| Pipeline | CPU | VAAPI | Ganho |
|---|---:|---:|---:|
| Decode + 1 fps + 640×360 + pipe | 29,13 s | 11,79 s | 2,47× |
| Analyzer completo | 39,58 s | 16,69 s | 2,37× |
| Eventos | 2 | 2 | idênticos |

O decoder `auto` agora prefere VAAPI para H.264 e H.265, com fallback para CPU.

## Filtro de luminosidade

No vídeo `camera-2026-11-05-0430.dav`, o intervalo 26:30–27:31 tinha apenas uma
mudança global de luminosidade (provável troca de IR para colorido no
amanhecer). O pico de score era 74,1% e a média do frame caiu de 112 para 66 em
um único segundo.

O filtro detecta `mean_delta >= 8` e `diff_ratio >= 0,35`, reseta o background e
descarta o frame. Após reanalisar, o evento falso de 1590–1651 s desapareceu; os
eventos de movimento real permaneceram.

## Thumbnail no ponto médio

As 85 thumbnails existentes foram regeradas no ponto médio de cada evento pelo
script `scripts/backfill_thumbnails.py`, sem reanálise. O evento de 570–592 s,
por exemplo, passou a usar o frame de 581 s (OSD 04:39:40), em vez do frame de
570 s.

A UI usa `?v=mid` nas URLs de thumbnail e o backend responde com
`Cache-Control: no-cache`, para evitar imagens antigas em cache. O teste de
navegador confirmou `naturalWidth=480` e `src` com `?v=mid`.

## Upload em chunks

- Um DAV de 130 MB foi enviado pelo domínio público em 16 chunks de 8 MB e
  concluído em 50,9 s, contornando o limite de ~100 MB do Cloudflare.
- O mesmo arquivo foi enviado pela UI usando o caminho de chunks; a lista foi
  atualizada com o novo vídeo e o progresso agregado foi exibido.
- A UI tenta novamente cada chunk até 3 vezes antes de reportar falha.

## Exposição pública

- `https://openoju.example.com` respondeu 200 em `/api/health`.
- Sem sessão, `/api/v1/auth/me` respondeu 401.
- Requisição Range no stream respondeu 206.
- Upload de arquivo pequeno e de arquivo de 130 MB em chunks funcionou via
  Cloudflare/NPM.

## Verificação do rebranding (Playwright)

Feita em `https://openoju.example.com` com sessão real, em desktop
(1440×900) e mobile (390×844).

- Login renderizou o símbolo e o wordmark OpenOju; título da aba `OpenOju`.
- Header mostrou o símbolo inline e o texto `OpenOju` em desktop e mobile; a
  navegação quebra em duas linhas no mobile sem sobrepor o wordmark.
- Lista de vídeos carregou os 8 vídeos e as 85 movimentações, com thumbnails
  em todos os cards.
- Detalhe do vídeo abriu player, resumo, timeline e eventos; `stream` respondeu
  `206` para vídeo local e para vídeo em S3 (redirecionado para o host novo).
- `manifest.webmanifest`, `favicon.ico`, `favicon-16/32`, `apple-touch-icon`,
  `icon-192/512`, `icon-maskable-512`, `mask-icon.svg` e `og-image.png`
  carregaram com as dimensões corretas.
- `og:image` e `twitter:image` usam URL absoluta (`https://openoju.example.com`),
  e o `og:image` respondeu `200 image/png` com 1200×630.
- O host legado `camera.example.com/videos` respondeu `301` para o host novo.
- Nenhuma ocorrência do nome antigo do produto ou do prefixo antigo de
  variáveis no texto das páginas de vídeos, perfis e administração.
- Erros de console observados são externos ou esperados: favicon do WhatsApp
  (extensão do navegador), Cloudflare Insights bloqueado pelo cliente e `401`
  em `/api/v1/auth/me` quando não há sessão.
