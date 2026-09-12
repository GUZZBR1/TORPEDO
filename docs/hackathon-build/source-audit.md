# Auditoria das fontes oficiais Plow

Revisão feita em 2026-09-12 para alinhar o contrato do Scout sem modificar ou reimplementar o Plow.

## Fontes

- `plow-pbc/latch` em `fcc04b48f35e40849738ddbb4b95a032f07503cb`.
- `plow-pbc/life-assistant-hermes-agent` em `5d60afa98b8a8a49d4269e94fbc375bda7dac33f` como exemplo atual de conteúdo de agente.
- Imagem base imutável já fixada no `Dockerfile` pelo commit `8710797b6409c77df560c6198407765d138ea617` e digest do registry.
- Agent Index Client já fixado em `87901f8b182a8a7c65ee3dd7267f8f835ee2a545`, com SHA-256 verificado no build.

## Contrato Latch confirmado

- `plow_read_skill` fornece o skill `camoufox-browsing`, cuja leitura é exigida pela descrição de abertura.
- `plow_browser_open` exige `origins`, aceita `headed` e devolve o handle privado `session`.
- `plow_browser_request` amplia origens e/ou autoriza IDs específicos de `credential_items`.
- `plow_browser` concentra `goto`, `click`, `fill`, `fill_secret`, `scroll`, `wait`, `back`, `use_page`, `screenshot`, `text`, `url`, `title`, `links`, `forms`, `tables` e `pages`.
- `plow_vault` permite apenas `list` e `describe`; o valor nunca é retornado. O uso acontece somente por `plow_browser`/`fill_secret`.
- `plow_browser_close` encerra a sessão e `plow_get_result` consulta chamadas deferidas.

O contrato atual também manda capturar screenshot após cada navegação, acompanhar `page_count` para popups e ler `failed_requests`. Embora Latch ofereça `eval`, o Scout o proíbe para manter a regra da especificação e impedir atalhos sobre UI ou segredos.
