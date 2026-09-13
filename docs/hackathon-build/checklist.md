# Checklist de construção do Scout

## Preferências de execução

- **Modo:** autônomo, conforme solicitado pelo usuário.
- **Verificação:** obrigatória ao fim de cada etapa; falhas são corrigidas antes do avanço.
- **Registro:** este arquivo é a fonte de verdade. Uma etapa só recebe `[x]` após sua verificação passar.
- **Git:** commits pequenos com o protocolo Lore e envio ao repositório remoto após marcos verificados.

## Etapas

- [x] **1. Reauditar especificação e implementação existente**
  - Escopo: reler `CODEX_BUILD_BRIEF.md` e `SCOUT_SPEC.md`, inspecionar todos os artefatos e executar a suíte inicial.
  - Proveniência: os dois documentos foram fornecidos ao agente durante a construção e não fazem parte deste repositório. Uma futura reauditoria independente exige que o proprietário os forneça novamente ou arquive cópias sanitizadas.
  - Resultado: lacunas registradas em `build-notes.md`; baseline de 15 testes aprovado.
  - Verificação: `python3 -m unittest discover -s tests -v`.

- [x] **2. Endurecer o núcleo determinístico e os contratos de entrada**
  - Escopo: corrigir atomicidade da inicialização/transação, rejeitar campos desconhecidos, validar tipos estritamente e validar referências entre missão, etapa e evidência.
  - Aceite: nenhuma escrita inválida ou campo não reconhecido é descartado silenciosamente; rollback é comprovado por teste.
  - Verificação: testes de banco, CLI e validação.
  - Resultado: 8 testes focados aprovados; rollback, tipos, campos e referências cruzadas cobertos.

- [x] **3. Completar o grafo de processo e os fatos observados**
  - Escopo: permitir ligações determinísticas entre etapas e registrar custos/prazos como fatos estruturados com proveniência observada, inferida ou desconhecida.
  - Aceite: ligações apontam apenas para etapas da mesma missão; custos e prazos observados exigem evidência.
  - Verificação: testes de grafo, deduplicação e fatos.
  - Resultado: 11 testes focados aprovados; links e fatos possuem validação, deduplicação e proveniência.

- [x] **4. Fechar invariantes da máquina de estados e retomada**
  - Escopo: exigir checkpoint/evidência/fronteira antes de `COMPLETE`, exigir bloqueador ao entrar em `BLOCKED` e preservar retomada pelo último checkpoint.
  - Aceite: estados inválidos são recusados deterministicamente e a retomada simulada mantém o ponto correto.
  - Verificação: testes de transição e perda simulada de sessão.
  - Resultado: 8 testes focados aprovados; bloqueio, resolução, checkpoint, conclusão e falha possuem gates explícitos.

- [x] **5. Fortalecer a barreira de segurança**
  - Escopo: ampliar ações e sinônimos de alto risco, impedir navegação descrita como ação consequencial e validar todo o objeto de ação.
  - Aceite: submit, compra, pagamento, assinatura, cancelamento, exclusão, publicação, comunicação externa e compromisso legal falham fechados.
  - Verificação: suíte golden e casos adversariais.
  - Resultado: 11 testes de segurança/contrato aprovados, inclusive inspeção segura e cliques ambíguos.

- [x] **6. Alinhar o contrato Hermes/Latch e a persona**
  - Escopo: conferir fontes oficiais atuais, documentar ciclo screenshot-first, autenticação por perfil/vault, extensão de origem, bloqueio e fechamento de sessão sem reimplementar MCP.
  - Aceite: o skill descreve chamadas diretas e uma ordem inequívoca para cada página materialmente nova.
  - Verificação: revisão contratual contra a especificação e fontes oficiais fixadas.
  - Resultado: contrato alinhado ao Latch atual e protegido por 3 testes textuais.

- [x] **7. Robustecer relatório e cenários completos simulados**
  - Escopo: relatório com observado/inferido/desconhecido, custos, prazos, bloqueadores não resolvidos e limite de efeito; três fluxos completos simulados.
  - Aceite: relatórios inválidos são recusados e os cenários público, autenticado e irreversível passam de ponta a ponta no núcleo determinístico.
  - Verificação: testes de relatório, contratos e E2E simulado.
  - Resultado: 5 testes focados aprovados; três fluxos completos simulados e relatório com fatos/proveniência.

- [x] **8. Verificar empacotamento, Agent Index e automação de qualidade**
  - Escopo: conferir Docker/Compose/s6/pin do cliente, adicionar verificações estáticas e CI sem novas dependências.
  - Aceite: configuração Compose válida, pin verificável, scripts compilam e CI reproduz a suíte.
  - Verificação: `compileall`, `docker compose config`, checksum e suíte completa; build real quando o daemon estiver disponível.
  - Resultado: checks estáticos aprovados, checksum oficial idêntico, imagem `scout:verify` construída e smoke test executado dentro dela.

- [x] **9. Completar documentação operacional e de demonstração**
  - Escopo: instalação, configuração, ciclo de missão, retomada, limites de segurança, comandos determinísticos e roteiro dos três demos.
  - Aceite: um novo operador entende o caminho instalar → conversar → enviar URL → receber rota e sabe quais gates dependem de Mac/credenciais.
  - Verificação: revisão dos comandos e links locais.
  - Resultado: runbook operacional, plano de demos e links do README protegidos por 3 testes.

- [x] **10. Auditoria final, limpeza, commit e publicação**
  - Escopo: executar todas as verificações disponíveis, revisar diff e riscos, marcar as etapas concluídas e enviar para `GUZZBR1/TORPEDO`.
  - Aceite: árvore Git limpa após o push e commit remoto corresponde ao local.
  - Verificação: suíte final, status Git e confirmação do remoto.
  - Resultado: marco `778ebed` e correções posteriores publicados; a reauditoria local de 2026-09-12 encontrou `main` limpa e alinhada com `origin/main` em `7827d66`.

## Gates externos (não falsificáveis localmente)

Estes itens não impedem concluir todo o trabalho executável neste computador, mas são necessários para a definição de pronto de produção/hackathon e permanecem explicitamente externos:

- [ ] Inicialização real do agente por Plow Chat com credenciais válidas.
- [ ] Reconhecimento real em um Mac conectado ao Plow Latch.
- [ ] Registro e telemetria confirmados no serviço Agent Index.
- [ ] Três demos reais: público, autenticado e fronteira irreversível.

As evidências para fechar estes gates devem ser registradas em
`docs/ACCEPTANCE_RECORD.md`; não marque um item apenas com base em logs locais
ou nos testes simulados.
