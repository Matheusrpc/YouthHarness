# Backlog do YoungCrowHarness

Frente: produto completo e sequência de entrega. Atualizado em 2026-10-03.

Este é o índice público do trabalho necessário para entregar a esteira definida na
[especificação aprovada](superpowers/specs/2026-10-03-ai-product-pipeline-design.md).
A base está publicada; a preparação de missões entrou na `main` pelo
[PR #18](https://github.com/Matheusrpc/YoungCrowHarness/pull/18). A execução autônoma ainda precisa
das entregas abaixo. Não há estimativa de prazo ou percentual de conclusão validada.

O público inicial é formado por desenvolvedores individuais e pequenos times com Claude Code
ou Codex. A primeira versão completa deve levar uma missão de uma a N features até uma versão
conjunta em produção verificada, em projeto novo ou migrado, com retomada pelo vault.

## Como acompanhar

- [Base entregue](#base-entregue)
- [Sequência das entregas](#sequência-das-entregas)
- [Pendências de prova da base](#pendências-de-prova-da-base)
- [Frente 2: execução e continuidade](#frente-2-execução-e-continuidade)
- [Frente 3: QA e integração](#frente-3-qa-e-integração)
- [Frente 4: release e operação](#frente-4-release-e-operação)
- [Aceite do produto completo](#aceite-do-produto-completo)
- [Extensões após o núcleo](#extensões-após-o-núcleo)

Os códigos `YC-*` identificam itens deste planejamento público. Eles não são missões ou PBIs
já importados no banco operacional. A decomposição em tarefas de código fica nos planos de cada
entrega. Um item planejado só fica pronto para desenvolvimento depois de ter DoR, DoD, dependências
e plano revisados. Três PBIs ativos é o limite inicial de trabalho em andamento; o backlog pode
ter quantos itens o produto exigir.

## Base entregue

| Capacidade | Estado e evidência |
|---|---|
| Setup e preservação do projeto | Instalador com preflight e testes de preservação; [primeira entrega](relatorios/2026-10-01-primeira-entrega.md) |
| Personalizer para projeto novo e existente | Entrevista retomável, auditoria e perfil; [ensaio](relatorios/2026-10-02-personalizer.md) |
| Vault, índices e integrações | Notas ligadas, especialista em integração e fontes; [integrações](relatorios/2026-10-01-integration-vault.md) e [verificador](relatorios/2026-10-02-vault-check.md) |
| Docling e referências | Documentos, HTML, áudio/vídeo e origem privada; [matriz](relatorios/2026-10-02-docling-ingestion.md) e [Claude](relatorios/2026-10-03-claude-docling.md). Anexos sem caminho exposto exigem registro explícito |
| Memória consultável | Markdown, Graphify opcional e retomada entre sessões/projetos; [isolamento de temas](relatorios/2026-10-02-memory-project-isolation.md) |
| Governança de skills, agentes e MCPs | Catálogo, auditoria e provas delimitadas por cliente; [matriz](relatorios/2026-10-02-capability-governance.md). Auditoria não concede autorização |
| Experimentação reversível | Baseline anterior ao setup e retorno preservando o trabalho do trial; [provas](relatorios/2026-10-02-reversible-adoption.md). Efeitos em serviços externos ficam fora do retorno de arquivos |
| Exemplo público | Quadro de entregas publicado e verificado; [piloto](relatorios/2026-10-03-public-pilot.md). Retomada do piloto no Claude ainda pendente |
| Frente 1: preparação de missões | Configuração, backlog, DoR/DoD, histórico e quatro skills; [provas](relatorios/2026-10-03-mission-foundation.md). Execução dos modelos ainda não verificada |

## Sequência das entregas

As frentes 1–4 preservam a numeração da especificação. A frente 2 tem três incrementos para
permitir verificar o executor antes de lhe dar uma fila de desenvolvimento e transferência.

| Ordem | Entrega | Resultado visível | Situação |
|---|---|---|---|
| 1 | Fundação das missões | Personalizar, configurar, preparar e consultar | Publicada |
| 2A | Executor limitado e adaptadores | Inspecionar o cliente e provar uma execução delimitada, com recibo e recuperação | Parcial: mecanismo implementado; perfis nativos bloqueados. [Provas e pendências](relatorios/2026-10-03-mission-runtime-adapters.md) |
| 2B | Fila e desenvolvimento | Puxar PBIs por prioridade, com três PBIs/três agentes e branches próprias | Planejada; depende de 2A |
| 2C | Continuidade | Pausar, retomar e transferir local/servidor sem duplicar responsabilidade | Planejada; depende de 2B |
| 3 | QA e integração | Revisão independente, testes, Playwright, correções e versão integrada | Planejada; depende de 2B; aceite conjunto inclui 2C |
| 4 | Release e operação | PR protegido, deploy manual/automático e produção verificada | Planejada; depende de 3 e 2C |
| Aceite | Produto completo | Percurso real nas combinações anunciadas, documentação e pacote público | Planejado; depende das frentes anteriores |

Os próximos três itens de implementação são `YC-201`, `YC-202` e `YC-203`. As provas pendentes
da base podem ocorrer quando houver acesso e limites explícitos; não autorizam chamadas por si só.

## Pendências de prova da base

| ID | Entrega | Dependência | Critério de aceite | Estado |
|---|---|---|---|---|
| YC-010 | Retomar o piloto público em sessão nova do Claude | Login válido e tentativa delimitada | Encontrar índices, UUIDs, revisão e produção observada sem receber o histórico inteiro; registrar resultado real | Bloqueado por autenticação na última tentativa |
| YC-011 | Provar as quatro novas skills nos clientes nativos | Instalação atual e sessão autorizada em cada cliente | Descobrir e aplicar `yc-personalizer`, `yc-config`, `yc-missao` e `yc-status`; preservar dados e distinguir preparo de execução | Pendente; integra a prova de YC-203 |

## Frente 2: execução e continuidade

PM responde por objetivo, prioridade e DoR/DoD; Tech Lead detalha interfaces e dependências.
Desenvolvimento implementa; QA produz a prova independente. Os papéis serão agentes na esteira.
Até ela existir, esses ritos são conduzidos nas sessões autorizadas.

| ID | Feature / PBI | Depende de | Critério de aceite | Estado |
|---|---|---|---|---|
| YC-201 | 2A: preflight e compatibilidade dos clientes | Frente 1 | Conferir cliente, versão, modelo/effort, autenticação selecionada e capacidades. Configuração desconhecida fica bloqueada, sem fallback ou chamada de modelo | Implementado; catálogo dinâmico e recusas testados. Perfis nativos continuam sem aceite de execução |
| YC-202 | 2A: execução limitada e recibos duráveis | YC-201 | Reservar operação antes de chamar; impor tempo e quantidade, registrar consumo observado, encerrar processos próprios e conservar resultado incerto sem repetir | Implementado; mecanismo determinístico em validação final |
| YC-203 | 2A: instalação, consulta e provas dos adaptadores | YC-202 | Provar cliente autenticado e API explícita quando houver acesso, em matriz por ambiente; consulta sem escrita e adoção preservada. Cada combinação sem prova permanece indisponível | Parcial; faltam provas de isolamento/autenticação nos perfis nativos. [Matriz](relatorios/2026-10-03-mission-runtime-adapters.md) |
| YC-204 | 2B: coordenador e fila priorizada | YC-203 | Uma missão ativa por repositório; três PBIs e três execuções como limites distintos; dependências e ordem persistidas. Sem item elegível, persistir espera | Planejado |
| YC-205 | 2B: branches e worktrees por PBI | YC-204 | Um escritor por checkout, base registrada, alterações do usuário preservadas, limpeza apenas de recursos próprios e recuperação após criação interrompida | Planejado |
| YC-206 | 2B: decisões de PM/Tech Lead e contexto dos agentes | YC-204, YC-205 | Validar propostas estruturadas e revisões; repriorizar somente PBIs não iniciados; avisar líderes uma vez por evento. Contexto reúne referências necessárias, sem ampliar escopo | Planejado |
| YC-207 | 2C: pausa, retomada e cancelamento | YC-206 | Encerrar despachos/processos, persistir consumo e tentativas, reconciliar efeito incerto e retomar sem repetição. Cancelamento explícito libera a vaga e conserva o trabalho | Planejado |
| YC-208 | 2C: pacote privado e troca de responsável | YC-207 | Transferir Git, estado, notas e evidências com hashes; excluir credenciais; importar pausado. Origem perde direito de retomar a geração entregue | Planejado |
| YC-209 | 2C: prova local/servidor nos dois sentidos | YC-208 | Transferência interrompida, repetida e confirmação perdida preservam um único responsável; contadores sobrevivem e sessão nova localiza o histórico | Planejado |

Aceite da frente 2: `yc-iniciar`, `yc-pausar`, `yc-retomar` e `yc-transferir` instalados e
verificados nas combinações anunciadas. A etapa 2A isolada fornece o mecanismo de execução e
diagnóstico; o início autônomo de missões depende de 2B. Transferência depende de 2C.

## Frente 3: QA e integração

| ID | Feature / PBI | Depende de | Critério de aceite | Estado |
|---|---|---|---|---|
| YC-301 | Revisão técnica e QA por PBI | YC-206 | Sessões independentes do implementador examinam diff, critérios, testes/build/análise pertinentes e resultados reais; defeito conhecido é reprovado | Planejado |
| YC-302 | QA visual e operacional por Playwright | YC-301 | Testar localhost, teclado, formulários e tamanhos relevantes contra referência aprovada; registrar capturas e ações; zero processos próprios restantes. Projetos sem interface registram não aplicável | Planejado |
| YC-303 | Autocorreção com limite de três ciclos | YC-301 | Implementação inicial mais até três correções; terceira reprovação bloqueia e avisa líderes. Falha operacional tem estado próprio; pausa, transferência ou novo ID não renovam tentativas | Planejado |
| YC-304 | Integração serial e aprovações por revisão | YC-205, YC-301, YC-303 | Integrar um PBI por vez; rejeitar conflito, base alterada e aprovação antiga; vincular pareceres ao commit, árvore, critérios e evidências | Planejado |
| YC-305 | Validação conjunta e aceite da versão | YC-302, YC-304 | Uma ou várias features formam uma versão; PM, Tech Lead e QA aprovam o conjunto. Defeito integrado retorna ao item responsável sem apagar histórico | Planejado |

## Frente 4: release e operação

| ID | Feature / PBI | Depende de | Critério de aceite | Estado |
|---|---|---|---|---|
| YC-401 | PR e promoção pela proteção da main | YC-305 | Respeitar checks/revisões, conferir árvore após merge e ligar artefato à revisão final; mudança de conteúdo invalida aprovações afetadas | Planejado |
| YC-402 | Deploy manual e automático | YC-401 | Manual como padrão e espera persistida; automático explícito usa os mesmos gates. Detectar workflows que publicam ao fazer merge e impedir promessa manual incompatível | Planejado |
| YC-403 | Verificação de produção e fechamento | YC-402 | Conferir revisão, saúde e fluxos críticos numa janela finita; só então marcar missão concluída e registrar timestamp, ambiente e evidências | Planejado |
| YC-404 | Falha de deploy e recuperação autorizada | YC-402 | Consultar operação incerta antes de repetir, respeitar teto de tentativas e provar retorno configurado. Migração de dados exige procedimento próprio | Planejado |
| YC-405 | Avisos e operação por eventos | YC-206, YC-403, YC-404 | Status/terminal expõem decisões e falhas; webhook opcional só para destino autorizado, com deduplicação, limite de tentativas e sem documentos/segredos | Planejado |

## Aceite do produto completo

| ID | Entrega | Depende de | Critério de aceite | Estado |
|---|---|---|---|---|
| YC-501 | Matriz de ponta a ponta | YC-010, YC-011, YC-209, YC-305, YC-405 | Projeto novo/migrado, uma/N features, ambos os clientes, local/servidor e conexões anunciadas percorrem o rito. Login indisponível fica pendente; simulação não vale como prova nativa | Planejado |
| YC-502 | Memória verificável da entrega | YC-501 | Sessão nova encontra tema, fontes, agentes/skills/MCPs, criação/refino/dev/QA/deploy, produção atual e próxima ação. Verificar vínculos/recibos de encerramento; não certificar texto livre como verdade | Planejado |
| YC-503 | Guias, demonstração e processos completos | YC-502 | README e guia PT/EN, exemplo público e diagramas cobrem zero, migração, configuração, missão, falhas, transferência, QA, deploy e saída. Mostrar o que está disponível e seus limites | Planejado |
| YC-504 | Publicação e manutenção do repositório | YC-503 | Versão identificável, notas de release, política de compatibilidade/migração, guia de contribuição e relato privado de vulnerabilidades; licença/créditos e pacotes revisados | Planejado |

DoR comum: objetivo observável; escopo pequeno; dependências conhecidas; referências acessíveis;
critérios testáveis; comandos de validação e autorizações do percurso definidos. Itens sem esses
dados permanecem em refinamento.

DoD comum: código e documentação revisados; testes pertinentes com saídas reais; evidências ligadas
ao item; README/guia/processo coerentes; integração protegida e retomada pelo vault. Para releases,
acrescentar versão, ambiente e produção verificada. Uma prova de biblioteca ou de documentação pode
terminar sem deploy de produto, declarando o alvo que realmente publicou.

Registrar horários UTC de criação, refinamento, desenvolvimento, revisão, QA, deploy e verificação,
preservando cada ocorrência. Etapas ainda não executadas ficam sem timestamp de conclusão.
Cada atualização deste backlog acompanha o PR que mudou seu estado e a prova correspondente.
Os 25 itens obrigatórios incluem o mecanismo 2A implementado e as provas nativas ainda abertas.
A contagem descreve o escopo do backlog, sem equivalência de esforço ou percentual de conclusão.

## Extensões após o núcleo

Estes candidatos permanecem visíveis para a visão de longo prazo. Precisam de desenho e aceite
próprios; não bloqueiam a primeira esteira completa acordada.

| ID | Candidato | Como decidir |
|---|---|---|
| YC-X01 | Avaliar claude-mem como adaptador opcional | Comparar recuperação, custo, privacidade, isolamento e uso nos dois clientes contra Markdown/Graphify. Preservar caminho de volta ao vault e fallback sem dependência obrigatória |
| YC-X02 | Atualização assistida de relações e índices | Propor relações com evidência e revisão; detectar fontes alteradas e reindexar apenas seleção autorizada. Medir melhoria de recuperação e evitar duplicar a verdade do vault |
| YC-X03 | Sincronização contínua entre máquinas | Avaliar somente se a transferência explícita não atender; resolver conflitos, privacidade e responsabilidade antes de automatizar |
| YC-X04 | Revisões imutáveis para plugins de marketplace | Verificar o que cada host permite fixar e provar revogação/atualização; não prometer reprodução com números de versão que o instalador não aplica |

Histórico durável no vault permite continuar além de uma sessão. Armazenamento, retenção e contexto
dos modelos continuam finitos; as extensões devem melhorar recuperação e navegação de forma mensurável.

## English overview

The foundation and mission preparation are published. Delivery 2A implements client preflight,
bounded execution and durable receipts, with [native isolation proofs still open](relatorios/2026-10-03-mission-runtime-adapters.md).
Both native profiles stay blocked. Next come the priority queue and isolated workspaces (2B), pause/resume/transfer
(2C), independent QA and integration (3), and protected release with verified production (4).

The 25 core backlog items include the implemented 2A mechanism, outstanding native proofs and
four final acceptance/public release items. Item counts are not effort estimates or completion percentages.
The tables above retain stable IDs, dependencies, acceptance criteria and status. Optional
claude-mem, assisted indexing, continuous synchronization and immutable marketplace pinning remain
separate candidates. Commands are documented as available only after installation and verification.
