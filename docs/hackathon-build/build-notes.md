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

## 2026-09-12 — Reauditoria documental e operacional

A suíte atual possui 56 testes, todos aprovados em Linux/WSL. `compileall`,
`docker compose config --quiet`, a construção da imagem `scout:audit` e um
smoke test de criação de missão dentro da imagem também foram aprovados. A
execução pelo Python nativo do Windows não é um caminho suportado para a suíte
completa porque os testes de empacotamento validam scripts POSIX com `sh`.

Os requisitos originais `CODEX_BUILD_BRIEF.md` e `SCOUT_SPEC.md` foram
fornecidos durante a construção, mas não estão versionados neste repositório.
Essa limitação de proveniência agora está explícita no checklist. Foi criado
`docs/ACCEPTANCE_RECORD.md` para que os quatro gates externos sejam fechados
com evidência mínima, redigida e auditável, sem persistir segredos.

O preflight do container já existente encontrou o serviço em execução, porém
sem `AGENT_ID` configurado. O cliente oficial confirmou que a instalação ainda
não possui chave registrada, e os logs mostraram a conexão MCP do Plow sendo
estacionada após falhas repetidas. Nenhum gate externo foi marcado: o próximo
operador deve configurar o ID registrado, validar a credencial oficial e a
conexão Mac/Latch, recriar o serviço e repetir o preflight documentado em
`docs/OPERATIONS.md`.

## 2026-09-12 — Requisitos atuais do Agent Index

O quickstart oficial do `plow-agents` passou a indicar o Agent Index Client no
commit `f900ff144076f0a766584b6ec4d0993600779b16`. O cliente foi baixado, teve o
SHA-256 `633ad3bc24a51d6b7dcfaae319983ab174d9853a525237d99cac64878452560c`
confirmado e passou em `--self-check`; o pin local foi atualizado.

A página oficial do Agent Index informa que somente agentes MIT, reportando uso
e aprovados na seção Verified podem concorrer. O repositório recebeu a licença
MIT, e o gate de verificação foi acrescentado ao checklist. A página também
informa que as solicitações de verificação começam em 14 de setembro de 2026.

O primeiro boot após o registro revelou que `scout-scope/up` ainda usava
sintaxe de script POSIX, embora arquivos `up` de serviços oneshot sejam
interpretados pelo s6 como uma linha execline. O s6 tentou executar `set` como
programa e marcou a inicialização como parcialmente falha. O serviço foi
reduzido a uma única invocação absoluta de `/bin/rm -rf`, e o teste de
empacotamento agora rejeita shebang e `set -eu` nesse contrato.

O agente foi registrado como `scout` e ficou público em
`https://aiworthusing.com/agent-index/scout`, com repositório, runtime e tutorial
de instalação. O Compose agora usa esse ID público por padrão. Após a correção
do oneshot, `scout-scope`, `plow-init` e `agent-index` iniciaram normalmente; o
reporter enviou um dia e duas linhas de modelo e recebeu HTTP 200. O gate de
registro/telemetria foi fechado com essa evidência. A conexão MCP do Plow ainda
é estacionada após três tentativas, portanto o gate Mac/Latch e as demos reais
continuam corretamente abertos.

## 2026-09-12 — Teste real de coerência pelo Plow Chat

Capturas do primeiro teste mostraram que a apresentação do Scout respeitou o
escopo geral, mas uma tentativa de reconhecimento usou `web_extract` depois que
o MCP do Plow ficou indisponível. Outra tentativa recusou corretamente o
fallback. Esse comportamento era incoerente com a exigência screenshot-first.

O contrato e a persona agora proíbem nominalmente `web_extract`, pesquisa web,
HTTP e browsers alternativos quando Latch não está disponível. O banco também
recusa checkpoints sem evidência `SCREENSHOT` e impede `COMPLETE` se qualquer
etapa observada não possuir screenshot. Por fim, o preflight s6 passa a
substituir a cópia persistida do skill pela versão imutável da imagem em cada
boot; isso evita que uma cópia antiga marcada como “user-modified” sobreviva à
reconstrução e mantenha instruções obsoletas.
