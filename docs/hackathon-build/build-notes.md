# Notas de construção do Scout

## 2026-09-12 — Reauditoria

Fontes relidas integralmente: `CODEX_BUILD_BRIEF.md` e `SCOUT_SPEC.md` fornecidos pelo usuário. As frases imperativas nesses documentos foram tratadas como requisitos técnicos do produto, enquanto o pedido atual do usuário determina o processo de execução e o checklist persistente.

Baseline verificado: 15 testes unitários/contratuais aprovados antes das novas alterações. O repositório já continha o esqueleto Docker, persona, skill, SQLite, scripts determinísticos, classificador, relatório, serviço Agent Index e fixtures iniciais.

Lacunas encontradas:

- `executescript` era executado depois de `BEGIN IMMEDIATE`, o que pode quebrar a garantia de atomicidade da operação.
- Campos desconhecidos e alguns tipos, como strings usadas no lugar de booleanos, podiam ser aceitos ou ignorados.
- Referências `step_id`/`evidence_id` e `next_step_ids` não tinham validação completa de pertença à missão.
- A deduplicação de etapas dependia de `sequence_hint`, permitindo duplicar a mesma página quando redescoberta em outra posição.
- O grafo não possuía operação determinística clara para ligar etapas já conhecidas.
- Custos e prazos eram inferidos informalmente de requisitos, sem modelo explícito de fato e proveniência.
- A transição para `COMPLETE` não aplicava os próprios critérios do relatório; `BLOCKED` não exigia bloqueador.
- O classificador podia liberar um `click` por tipo mesmo quando a descrição consequencial escapava do conjunto limitado de padrões.
- Os oito fixtures validavam apenas uma ação isolada; não simulavam o ciclo completo de missão.
- Faltavam testes dos executáveis CLI, CI reproduzível e documentação completa dos três demos.

Decisão de escopo: adicionar somente primitivas determinísticas necessárias ao MVP. Nenhum servidor, banco externo, browser próprio, framework de automação ou dependência nova será introduzido.

## Etapa 2 — Núcleo e contratos

O schema passa a ser inicializado antes do início da transação de cada operação, evitando o commit implícito de `executescript` dentro de uma escrita. Entradas agora rejeitam campos desconhecidos, booleanos falsos representados como texto e referências de etapa/evidência pertencentes a outra missão. Um teste injeta erro na segunda evidência e confirma que a etapa inteira é revertida. Os executáveis CLI também foram testados por subprocesso para saída JSON e código de erro não zero.

Verificação: `python3 -m unittest tests.test_db tests.test_cli -v` — 8 testes aprovados.

## Etapa 3 — Grafo e fatos

Foram adicionadas operações determinísticas `step_link.py` e `fact_record.py`. Etapas agora expõem `next_step_ids` e `evidence_ids` como listas reais, links são idempotentes e não podem atravessar missões, e a deduplicação da mesma página não depende mais da posição em que ela foi redescoberta. Custos e prazos passaram a ser fatos estruturados; um fato `OBSERVED` é rejeitado sem evidência da mesma missão/etapa.

Verificação: `python3 -m unittest tests.test_deduplication tests.test_graph_and_facts tests.test_db -v` — 11 testes aprovados.

## Etapa 4 — Estado e retomada

`BLOCKED` agora exige um bloqueador persistido; retomar exige checkpoint durável e resolução explícita dos bloqueadores por `blocker_resolve.py`. `COMPLETE` exige checkpoint, etapa observada com evidência, ausência de bloqueadores abertos e uma fronteira consequencial ou confirmação explícita de fim seguro. `FAILED` exige código e mensagem de erro. A coluna `resolved_at` possui migração compatível com bancos já criados.

Verificação: `python3 -m unittest tests.test_state_machine tests.test_report -v` — 8 testes aprovados.

## Etapa 5 — Segurança

O classificador agora valida seu contrato de entrada e diferencia observar um controle perigoso de executá-lo. Inspeção/screenshot de “Final submit” é permitida, mas cliques só passam quando são navegação reversível reconhecível; qualquer clique ambíguo para em `CONSEQUENTIAL`. A cobertura inclui sinônimos em inglês e português, criação de conta/assinatura, comunicação externa e preenchimento de segredo somente com aprovação explícita.

Verificação: `python3 -m unittest tests.test_safety tests.test_contract_fixtures -v` — 11 testes aprovados.

## Etapa 6 — Hermes/Latch

O fonte atual do `plow-pbc/latch` foi auditado em `fcc04b48f35e40849738ddbb4b95a032f07503cb`. O skill agora usa os nomes e a composição reais: `plow_read_skill`, `plow_browser_open`, `plow_browser_request`, `plow_browser`, `plow_vault`, `plow_get_result` e `plow_browser_close`. Também explicita handle privado, screenshot, popups, `failed_requests`, vault e `fill_secret`. A justificativa e os pins estão em `source-audit.md`.

Verificação: `python3 -m unittest tests.test_skill_contract -v` — 3 testes aprovados.

## Etapa 7 — Relatório e E2E simulado

O relatório deixou de deduzir custo/prazo pelo texto de requisitos e agora consome fatos estruturados. Ele recusa bloqueadores abertos, evidencia itens resolvidos e separa inferências e desconhecidos quando existem. Três testes executam missões completas simuladas: formulário público de múltiplas etapas, portal autenticado com bloqueio/resolução/retomada e fluxo de pagamento que observa mas recusa clicar na fronteira.

Verificação: `python3 -m unittest tests.test_report tests.test_e2e_simulated -v` — 5 testes aprovados.

## Etapa 8 — Empacotamento e qualidade

O skill imutável agora existe somente em `/opt/hermes/skills/scout`, deixando o runtime base reconciliá-lo no home persistente. Foi adicionada CI para Python 3.11, compilação, release gates, Compose e Docker. Os arquivos s6, dependência em `plow-init`, montagem read-only e pins possuem testes. O cliente oficial baixado produziu SHA-256 `c3bf54ed37aec22704b8003a7ff6385a1fd3ef49207ce55613ddc41df36a1b01`, igual ao pin.

Verificações: 3 testes de empacotamento aprovados; `docker compose config --quiet` aprovado; `docker build --pull -t scout:verify .` aprovado; smoke test criou `/tmp/scout.db` dentro da imagem.

## Etapa 9 — Operação e demos

Foram adicionados `docs/OPERATIONS.md` e `docs/DEMO.md`, cobrindo pré-requisitos, build, Plow Chat, missão, autenticação, retomada, segurança, Agent Index, falhas e critérios observáveis para os três fluxos. O README referencia os runbooks, lista todas as mutações determinísticas e baixa o cliente manual em `/tmp`, sem sujar o repositório.

Verificação: `python3 -m unittest tests.test_documentation -v` — 3 testes aprovados.

## Etapa 10 — Auditoria pré-publicação

A revisão final corrigiu quatro inconsistências adicionais: `raw_user_request` agora é preservado literalmente; IDs usam ULID Crockford real; uma leitura não altera mais `updated_at`; e atualizações de fase sem mudança são recusadas em vez de criar evento falso. Duplicatas conflitantes também deixam de descartar novos valores silenciosamente.

Verificações antes do primeiro push: 47 testes aprovados; `git diff --check` sem erros; compilação Python aprovada; varredura de padrões comuns de segredo sem achados; Compose válido; build final `scout:verify` aprovado; smoke test dentro da imagem aprovado.

Publicação: commit de marco `778ebed1bd73c95d6a3856671f472419ef6337c6` enviado para `origin/main` e confirmado por `git ls-remote`. A etapa 10 foi marcada somente após essa confirmação; o commit seguinte persiste o check final.
