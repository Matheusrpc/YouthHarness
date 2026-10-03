# Mission runtime adapters implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Executar e recuperar uma verificação delimitada dos clientes Claude Code e Codex, com autenticação explícita, limites e recibos privados, preparando o mecanismo que a fila de missões usará.

**Architecture:** Estender a CLI e o SQLite existentes com observações de cliente e execuções identificáveis. Adaptadores traduzem uma configuração congelada em argumentos estruturados; um controlador local reserva a operação, supervisiona o processo e registra a evidência. A consulta continua somente leitura e o início autônomo de missões permanece indisponível até a entrega 2B.

**Tech Stack:** Python 3.11+, biblioteca padrão, SQLite, clientes oficiais instalados, setup Bash e `unittest`. Windows e Linux. Sem SDK de modelo, servidor de coordenação ou dependência nova de runtime.

**Spec:** [Esteira de produto com agentes de IA](../specs/2026-10-03-ai-product-pipeline-design.md), aprovada. Este plano cobre o incremento 2A da frente 2 e os itens [YC-201–YC-203](../../BACKLOG.md#frente-2-execução-e-continuidade).

Frente: executor limitado e adaptadores. Plano aprovado pelo mantenedor. Implementação parcial:
catálogo dinâmico, mecanismo delimitado e recibos implementados; provas de isolamento nativas
continuam abertas e as chamadas reais estão bloqueadas. Nenhum turno foi enviado a fornecedor.
Método: implementação inline, um escritor e revisão independente ao final. Resultados e desvios
estão no [relatório da entrega](../../relatorios/2026-10-03-mission-runtime-adapters.md).

## Global Constraints

- “Três PBIs por padrão, configurável.” “Três simultâneas por padrão, configurável e separado do limite de PBIs.” Esta entrega prova uma execução por vez; a fila e suas reservas concorrentes pertencem a 2B.
- “Até três ciclos de correção e revalidação por PBI.” O diagnóstico de cliente não inicia nem consome correção de PBI.
- “Uma ativa por repositório; outras podem ser preparadas; uma a N features.” `prepared` continua sem adquirir vaga de missão ativa nesta entrega.
- “Somente após produção verificada.” Nenhum resultado de `client check` pode mudar a missão para `completed`, iniciar PBI, fazer merge ou declarar produção.
- Clientes autenticados são o padrão; API é escolha explícita pelos mesmos clientes oficiais. Não há JEV, fallback de modelo/conexão ou captura de tokens de assinatura.
- Modelo, esforço, limite de tempo, quantidade e eventual orçamento são escolhas explícitas. Preservar solicitado versus observado; informação ausente continua não observada.
- Intenção durável antecede efeito externo. Resultado incerto não admite repetição automática. Pausa ou nova sessão não apaga consumo.
- Um escritor por checkout. O subprocesso de prova não escreve no checkout, banco, recibos, credenciais ou configurações do coordenador. Combinação incapaz de impor o escopo exigido permanece sem suporte.
- Comandos usam lista de argumentos e `shell=False`; texto de modelo/documento não é executado como shell. Valores de credencial não aparecem em argumentos, erros, evidências ou Git.
- Reusar helpers de caminhos, privacidade e hash. Preservar notas humanas, UUIDs, configuração global e baseline do trial; atualizar README/guia PT/EN com `humanizer` e design existente.

## Review Focus

1. Ambiente herdado contém credencial API ou configuração gerenciada conflitante: nunca mudar conexão/cobrança silenciosamente. Prova na tarefa 1; limites não imponíveis bloqueiam na tarefa 2.
2. Processo termina após efeito externo e antes do recibo: repetir o UUID consulta a intenção e não cobra de novo; novo UUID também não contorna uma incerteza pendente do mesmo diagnóstico. Prova na tarefa 2.
3. Cliente lança descendente, PID é reutilizado ou supervisor cai: somente processos de identidade comprovada podem ser encerrados; enquanto houver dúvida, conservar reserva e bloqueio. Prova na tarefa 2.
4. Cliente muda binário, política, versão ou protocolo entre inspeção e execução: invalidar observação anterior e revalidar imediatamente antes do spawn. Provas nas tarefas 1 e 2.
5. Saída contém JSON duplicado, segredo, evento truncado ou sucesso sem término válido: saída limitada, erro sanitizado e recibo sem sucesso inventado. Provas nas tarefas 1–3.

## Escopo e sequência

Este incremento entrega `client inspect`, `client check` e `client runs` como operações da CLI
existente e orientação em `yc-config`/`yc-status`. `client check` executa um diagnóstico fixo,
em contexto sintético explicitamente selecionado, para conferir o contrato do adaptador. Não
aceita prompt de desenvolvimento livre. A compatibilidade comprovada é a do diagnóstico e do
perfil de ferramentas testado; não comprova permissões de um futuro worker de desenvolvimento.

2B acrescentará fila, reservas globais, contexto de produto, propostas PM/Tech Lead e worktrees
de PBI; deverá provar os perfis de desenvolvimento/revisão antes de habilitá-los. 2C acrescentará
pausa, cancelamento e transferência. QA, release e avisos externos permanecem nas frentes 3/4.
Os [itens do backlog](../../BACKLOG.md) mantêm essas dependências explícitas.

Não alterar instruções globais, instalar clientes, copiar caches de login ou escolher modelo
pelo usuário. Ler documentação oficial e ajuda da versão instalada durante a implementação;
nenhuma flag nova deve ser presumida a partir de um exemplo antigo. Evidências anteriores de
governança e memória informam o desenho, mas não certificam o novo adaptador.

## Arquivos e reaproveitamento

| Caminho | Responsabilidade |
|---|---|
| `scripts/mission_clients.py` (novo) | Inspeção limitada, tradução por cliente, validação do protocolo e metadados observados |
| `scripts/mission_process.py` (novo) | Processo supervisionado e encerramento dos recursos próprios |
| `scripts/mission_runs.py` (novo) | Intenções, transições, reconciliação e consulta dos recibos |
| `scripts/mission_store.py` | Migração transacional aditiva de esquema 1 para 2; preservar registros/eventos existentes |
| `scripts/missions.py`, `scripts/mission_vault.py` | Entradas CLI, status e projeções privadas do diagnóstico |
| `tests/runtime_fixtures.py`, `tests/fixtures/mission_client.py` (novos) | Projetos pequenos e cliente sintético determinístico, sem rede ou fornecedor |
| `tests/test_mission_clients.py`, `tests/test_mission_runs.py`, `tests/test_mission_process.py` (novos) | Contratos, recuperação, limites e supervisão real do processo sintético |
| `tests/smoke_mission_runtime.py` (novo) | Adoção e execução instalada; modo nativo separado e explicitamente limitado |
| `tests/test_setup.py`, `tests/smoke_clients.py` | Instalação/preservação e descoberta das skills de missão |
| `setup.sh`, `skills-lock.json`, `.github/workflows/test.yml` | Distribuir os helpers e verificar Linux/Windows sem chamadas reais de modelo no CI |
| `skills/yc-config/SKILL.md`, `skills/yc-status/SKILL.md` | Ensinar diagnóstico e leitura de resultados; revisar wrappers apenas se seus contratos mudarem |
| `README.md`, `docs/USAGE.md`, `docs/BACKLOG.md` | Uso implementado, matriz de suporte e estado do produto |

Reusar `mission_config.normalize_config`, `config_digest`, `mission_store.reader/transaction`,
`document_store.safe_path/verify_private_storage/atomic_write`, `adoption_fs.hash_file` e
`capabilities.audit/parse_json/canonical`. Inspecionar `tests/smoke_clients.py` e
`tests/smoke_capabilities.py` antes de implementar descoberta e encerramento; extrair somente o
helper realmente compartilhado. Não refatorar adoção, Docling ou Graphify como parte deste plano.

## Contratos comuns

### Inspeção e configuração

`inspect_client(root: Path, client: str, executable: Path) -> dict` usa apenas operações locais
de versão/ajuda/metadados conhecidas, com tempo e saída limitados. Retorna `client`, `version`,
`executable_sha256`, `protocol`, `policy_digest`, `connection_conflicts`, `gaps` e
`model_compatibility: not_verified`. Não abre login, não chama modelo/MCP e não grava no projeto.
Campo que não puder ser observado fica nulo com pendência. Inspeção não pode elevar permissões.

`build_check(agent: dict, observation: dict, manifest: dict) -> dict` retorna o plano de processo:
`argv: list[str]`, `cwd: str`, `stdin: bytes`, `timeout_seconds: int`, `output_limit_bytes: int`,
`client`, `connection`, `requested_model`, `requested_effort`, `policy_digest` e
`credential_env: str | None`. Este objeto não contém valores de credenciais e não é executável
se houver pendência de versão/protocolo/política. O segredo, quando necessário, é resolvido
somente no ambiente do filho e nunca serializado; o adaptador deve comprovar a precedência.

Valores low/medium/high são traduzidos somente quando suportados pela combinação testada;
`native` conserva o valor explícito. Pedido desconhecido gera `unsupported_combination`.
Modelos escolhidos pelo usuário podem passar por uma prova explicitamente autorizada sem
compatibilidade previamente confirmada; isso não equivale a habilitar missões autônomas.

### Manifesto do diagnóstico

Entrada JSON com chaves exatas: `schema_version: 1`, `mission_id`, `mission_revision`, `role`,
`operation_id`, `authorization_ref`, `agent_seconds`, `max_runs: 1`, `api_budget_usd` e `fixture_id`.
UUIDs, revisão inteira positiva, papel configurado e autorização textual não vazia são obrigatórios.
`fixture_id` escolhe apenas o diagnóstico interno versionado `echo-v1`; não aceita caminho, URL,
shell ou prompt arbitrário. A configuração vem do snapshot da missão, e seu digest entra no recibo.

Tempo deve ser positivo e não superar `limits.agent_seconds`; configuração incompleta bloqueia.
API exige orçamento decimal positivo dentro do orçamento da missão, estimativa/reserva documentada
e controles observáveis. Estimativa não é teto exato de fatura; se o controle exigido não puder
ser aplicado, bloquear a combinação. Assinatura registra uso disponível e custo desconhecido.
O manifesto registra a autorização do operador; conteúdo retornado pelo agente não pode criá-la.

Antes de chamar, usar uma fixture privada criada pelo coordenador com um nonce e uma resposta
JSON esperada. O perfil de prova permite apenas o mínimo necessário a esse diagnóstico e deve
impedir escrita no checkout/estado, rede não prevista e delegação de agentes fora do supervisor.
Worktree por si só não impõe essa fronteira. Provar permissão/recusa em ambiente sintético ou
classificar o perfil como `unsupported`; não instalar contêiner/serviço para contornar o gate.

### Estado e recibos

O esquema 2 conserva as quatro tabelas atuais e acrescenta `agent_runs`, `agent_run_events`
e `agent_run_projections`.
`agent_runs` guarda `id`, `mission_id`, `mission_revision`, `operation_id` único, `request_hash`,
`revision`, `state`, `snapshot`; `agent_run_events` guarda sequência, UUID, run, operação da
transição, revisão anterior/nova, horário UTC, tipo, payload canônico e `projection_state`.
`agent_run_projections` guarda caminho, SHA-256 e sequência com FK para `agent_run_events`;
não reutilizar a FK da tabela `projections`, que pertence aos eventos de preparação. Identidade do projeto
continua em `metadata`; UUIDs e revisões são conferidos em cada fronteira de escrita.

Estados: `reserved`, `running`, `succeeded`, `failed`, `interrupted`, `uncertain`.
Guardar intenção antes do spawn. `reserved` sem prova de que o spawn não ocorreu também exige
reconciliação após queda; não presumir ausência de efeito. `uncertain` bloqueia outra prova no
mesmo projeto até resolução explícita com evidência. Interrupção só é terminal quando término
dos recursos próprios e resultado externo estão conciliados; caso contrário permanece incerta.

Recibo registra propósito `client_check`, referências e hashes, início/fim, processo e dono,
cliente/versão, conexão, modelo/effort pedidos e observados, capacidades pedidas/observadas,
contadores, consumo quando disponível, código de saída, motivo e evidência. O esquema de
diagnóstico nunca grava aprovação de PBI ou produção. Saídas arbitrárias não são publicadas.

Projeções em `vault/local/missions/<mission-uuid>/runs/<run-uuid>.md` usam UUID, índice, revisão e
links para missão/configuração. Gerar microíndice `runs/index.md`. Preservar hash e edições humanas
com o mecanismo existente; falha após commit deixa projeção pendente recuperável. `client runs`
e `yc-status` consultam sem reparar, migrar ou atualizar metadados.

### Interfaces entre tarefas

- `decode_result(client: str, events: list[dict], expected_nonce: str) -> dict`: resultado normalizado, somente campos permitidos; pedido e observado separados.
- `supervise(plan: dict, *, on_started, stop_requested) -> dict`: executa o plano validado; callbacks locais, sem lógica de modelo; retorno com saída limitada, estado e prova de encerramento.
- `reserve_check(root: Path, manifest: dict, observation: dict) -> dict`: reserva transacional ou retorna recibo anterior; mesmo UUID com conteúdo diferente é conflito.
- `transition_run(root: Path, run_id: str, event: dict, expected_revision: int, operation_id: str) -> dict`: transição validada, idempotente e com CAS; evento inesperado é recusado.
- `check_client(root: Path, manifest: dict, executable: Path) -> dict`: preflight, reserva, supervisão e conclusão; não chama novamente ao encontrar operação anterior.
- `reconcile_check(root: Path, run_id: str, evidence: dict, expected_revision: int, operation_id: str) -> dict`: exige evidência de processo/efeito; se ela não basta, conserva `uncertain`.
- `list_runs(root: Path, mission_id: str) -> list[dict]`: somente leitura; banco ausente retorna lista vazia.
- `project_run(root: Path, run_id: str) -> dict`: projeta eventos confirmados e devolve `current`, `pending` ou `conflict`; preserva edições humanas. Chamado ao concluir/repetir `check` ou `reconcile`, nunca por consultas.

## Task 1: YC-201 — preflight e tradução por cliente

**Files:** criar `scripts/mission_clients.py`, `tests/test_mission_clients.py`,
`tests/runtime_fixtures.py`, `tests/fixtures/mission_client.py`; modificar `README.md`, `docs/USAGE.md`.

**Interfaces:** consome configuração normalizada e auditoria existentes. Produz
`inspect_client`, `build_check`, `decode_result` conforme contratos acima. A fixture oferece
modos `version`, `help`, `success`, `malformed`, `secret`, `hang`, `child` e `crash`, selecionados
apenas nos testes. `RuntimeCase` estende `MissionCase` e oferece `make_manifest()` e
`fake_observation()` com UUIDs, modelo fictício, tempo de dez segundos e `max_runs: 1`.

- [x] **Step 1: escrever os testes de contrato e recusa.**

```python
def test_inspection_never_verifies_model_or_changes_project(self):
    before = self.snapshot()
    result = inspect_client(self.root, 'codex', self.fake_executable)
    self.assertEqual(result['model_compatibility'], 'not_verified')
    self.assertEqual(before, self.snapshot())

def test_conflicting_api_environment_blocks_authenticated_check(self):
    with self.conflicting_api_environment():
        with self.assertRaisesRegex(ValueError, 'connection_conflict'):
            build_check(self.agent, self.fake_observation(), self.make_manifest())
```

Definir `fake_executable` e o context manager na fixture: ambiente isolado com valor de credencial
fictício; este valor deve estar ausente em toda saída. Acrescentar
`test_unknown_effort_is_not_downgraded`, `test_changed_binary_invalidates_observation`,
`test_managed_policy_gap_blocks_check`, `test_duplicate_or_truncated_json_is_rejected` e
`test_model_mismatch_is_not_success`. Fixar como asserts: zero despachos no erro, argumentos
em lista, modelo pedido preservado, campos desconhecidos/duplicados rejeitados e política
alterada invalidada. Testar Codex e Claude, authenticated e API, sem rede.

- [x] **Step 2: executar o RED.** `python -m unittest discover -s tests -p test_mission_clients.py -v` deve falhar por ausência dos adaptadores/contratos.
- [x] **Step 3: implementar as três funções e o simulador.** Consultar versão/ajuda locais e fontes oficiais para mapear apenas protocolos compreendidos; anotar lacunas. Proibir shell, fallback e leitura/serialização de credenciais na inspeção. Usar parser JSON existente e limite de 1 MiB por evento/8 MiB por execução para a prova; atingir o limite encerra o diagnóstico com erro explícito.
- [x] **Step 4: repetir o comando e verificar GREEN.** Nenhum teste envia prompt a fornecedor. Documentar o diagnóstico como preparação do adaptador, ainda sem executor disponível.
- [x] **Step 5: commit por caminhos explícitos.** Mensagem `feat: validate mission client execution contracts`.

## Task 2: YC-202 — execução limitada e recuperação

**Files:** criar `scripts/mission_runs.py`, `scripts/mission_process.py`,
`tests/test_mission_runs.py`, `tests/test_mission_process.py`; modificar
`scripts/mission_store.py`, `scripts/mission_vault.py`, `tests/runtime_fixtures.py`,
`tests/fixtures/mission_client.py`, `tests/test_missions.py`, `README.md`, `docs/USAGE.md`.

**Interfaces:** consome os três adaptadores da tarefa 1 e as fronteiras de armazenamento
existentes. Produz as operações de runs, `project_run` e `supervise` descritas acima. `make_manifest()`
deve apontar para uma missão `prepared` criada pelos helpers reais da fundação.

- [ ] **Step 1: escrever os testes de reserva, efeito e migração.**

```python
def test_replay_never_starts_a_second_process(self):
    manifest = self.make_manifest()
    first = check_client(self.root, manifest, self.fake_executable)
    again = check_client(self.root, manifest, self.fake_executable)
    self.assertEqual(first['id'], again['id'])
    self.assertEqual(self.fake_spawn_count(), 1)

def test_uncertain_run_keeps_reservation_and_blocks_new_uuid(self):
    manifest = self.make_manifest()
    self.crash_after_external_start(manifest)
    recovered = check_client(self.root, manifest, self.fake_executable)
    self.assertEqual(recovered['state'], 'uncertain')
    self.assertEqual(list_runs(self.root, manifest['mission_id'])[0]['state'], 'uncertain')
    with self.assertRaisesRegex(ValueError, 'unresolved_run'):
        check_client(self.root, self.make_manifest(), self.fake_executable)
```

Implementar os helpers de contagem/queda na fixture por marcador privado e subprocesso real;
não substituir a fronteira de persistência por mocks. Acrescentar
`test_schema_one_migration_rolls_back_atomically`, `test_status_does_not_migrate_schema_one`,
`test_same_operation_different_payload_conflicts`, `test_stale_revision_or_policy_does_not_spawn`,
`test_spawn_failure_proven_before_effect_is_failed`, `test_unproven_process_identity_is_not_killed`,
`test_timeout_reaps_owned_child_only`, `test_output_limit_terminates_owned_process`,
`test_unknown_cost_is_not_zero`, `test_reconcile_requires_evidence` e
`test_projection_failure_recovers_without_second_dispatch`.

Asserts adicionais: notas humanas preservadas; migração mantém missões/eventos/UUIDs; erro não
contém segredo fictício; transição repetida tem um evento; consumo não é zerado por reconciliação;
missão permanece `prepared`, com `runnable: false`; processo alheio permanece vivo e processos
próprios chegam a zero. Um recibo válido exige término do protocolo além de exit code zero.

- [ ] **Step 2: executar o RED.** `python -m unittest discover -s tests -p "test_mission_*.py" -v` deve apontar funções/transições novas ausentes; registrar as falhas exatas.
- [ ] **Step 3: implementar reserva/transições e migração aditiva.** `reader` aceita esquemas conhecidos sem migrá-los. A primeira escrita de run cria as três tabelas e atualiza metadata na mesma transação; rollback conserva esquema 1 utilizável. Não apagar tabelas nem fazer upgrade pelo status. Uma reserva não conciliada bloqueia outro check no projeto, inclusive com novo UUID. Repetir `check` após queda concilia o estado conhecido sem novo spawn; quando faltar prova, registra `uncertain`. Consultas apenas mostram a pendência.
- [ ] **Step 4: implementar supervisão e reconciliação.** Reservar antes de iniciar. Revalidar binário/política/configuração. Identificar processo/grupo e início, limitar stdout/stderr durante leitura, aplicar deadline monotônico e encerrar em `finally`. Linux usa grupo próprio com perfil que impeça descendentes de escapar; Windows precisa conter a árvore de processos antes de executar o filho, com Job Object ou controle nativo equivalente testado. PID sozinho e `taskkill`/kill genérico não provam propriedade. Plataforma sem contenção verificável retorna `unsupported` antes da chamada.
- [ ] **Step 5: persistir recibos e projeções; verificar GREEN.** Repetir o comando da etapa 2 e executar `python -m unittest discover -s tests -p test_missions.py -v`. Comparar árvores antes/depois de leitura e conferir zero processos próprios. Atualizar uso e limitações PT/EN.
- [ ] **Step 6: commit por caminhos explícitos.** Mensagem `feat: supervise bounded client checks with durable receipts`.

## Task 3: YC-203 — CLI instalada, consulta e matriz de provas

**Files:** modificar `scripts/missions.py`, `tests/test_missions.py`, `tests/test_setup.py`,
`tests/smoke_clients.py`, `setup.sh`, `skills-lock.json`, `.github/workflows/test.yml`,
`skills/yc-config/SKILL.md`, `skills/yc-status/SKILL.md`, `README.md`, `docs/USAGE.md`,
`docs/BACKLOG.md`; criar `tests/smoke_mission_runtime.py`,
`docs/relatorios/2026-10-03-mission-runtime-adapters.md` e
`docs/medicoes/2026-10-03-mission-runtime-adapters.json` durante a execução.

**Interfaces:** consome as operações das tarefas 1/2. Produz:

```text
python scripts/missions.py client inspect --client codex --executable PATH --json
python scripts/missions.py client check --manifest RELATIVE_PATH --executable PATH --json
python scripts/missions.py client runs --mission M001 --json
python scripts/missions.py client reconcile --run UUID --evidence RELATIVE_PATH --expected-revision N --operation-id UUID --json
```

Erros são códigos sanitizados e retornam status de processo não zero. `client inspect`/`runs`
nunca criam configuração, banco, vault ou diretório. O manifest contém a operação; argumentos
da CLI nunca recebem segredo. `yc-config` orienta inspeção, seleção e prova autorizada;
`yc-status` mostra último resultado e bloqueios. Não instalar `yc-iniciar` nesta entrega.

- [ ] **Step 1: escrever testes de instalação/CLI e smoke.** `test_runtime_helpers_preserve_existing_install`, `test_runtime_cli_readonly_on_fresh_project`, `test_cli_does_not_echo_client_secret`, `test_native_probe_requires_explicit_manifest` e `test_skill_entries_do_not_start_mission` verificam seleção Claude/Codex/both, helper ausente/incompatível, nenhum overwrite em migração/force e zero chamadas de modelo implícitas.
- [ ] **Step 2: executar o RED.** `python -m unittest discover -s tests -p test_setup.py -k runtime -v` e `python -m unittest discover -s tests -p test_missions.py -k client -v`; esperar ausência dos helpers/entradas CLI.
- [ ] **Step 3: ligar operações à CLI e ao setup.** Validar manifesto dentro da raiz, preservar privacidade e catálogo; atualizar hashes/dependências dos arquivos afetados. Exibir `check_available` e a prova específica de cliente sem mudar `runtime_available/runnable` da missão para verdadeiro. Atualizar o status sem reinterpretar recibos históricos.
- [ ] **Step 4: executar o smoke determinístico nos dois sistemas.** `python -B tests/smoke_mission_runtime.py --root CAMINHO_CURTO_AUSENTE_FORA_DO_GIT --client both` usa apenas o simulador. Deve adotar consumidor novo/existente, configurar/preparar, inspecionar, executar uma vez, repetir sem spawn, provocar timeout/queda, consultar/conciliar e retornar pelo trial. Conferir árvore, Git, arquivos humanos e perfil global preservados. Não alterar o contador de correções do PBI.
- [ ] **Step 5: provar descoberta nativa e preparar a matriz.** Estender `tests/smoke_clients.py` para as quatro skills da fundação. Separar descoberta sem modelo de aplicação numa conversa. Registrar OS, cliente/versão/binário, modelo/effort, conexão, perfil/política, escopo de capacidades, resultado, limites e data. Cada célula será `verified`, `failed`, `unsupported` ou `not_run`; matriz sem prova real não anuncia suporte.
- [ ] **Step 6: executar provas reais somente com entrada autorizada.** Modo separado `python -B tests/smoke_mission_runtime.py --native-manifest RELATIVE_PATH` exige modelo/configuração e manifesto de cada tentativa. Conferir login pela ferramenta oficial; se faltar, registrar pendência sem repetir. Cobrir Codex/Claude autenticados e API opcional em ambientes disponíveis, com uma execução por manifesto e limites definidos antes de chamar. Ausência de credencial conserva a célula pendente. Prova de API nunca usa credencial de assinatura. Não habilitar perfil de desenvolvimento com base nesta prova de diagnóstico.
- [ ] **Step 7: verificar a entrega.** Linux: `python -m unittest discover -s tests -v`. Windows: `python -B tests/windows_fixture_runner.py -m unittest discover -s tests -p "test_mission*.py" -v` e o smoke pelo mesmo wrapper. CI usa simuladores; provas pagas nunca rodam em PR. Registrar resultados, falhas/skip e zero processos próprios restantes. Revisar diff completo em contexto independente uma vez; corrigir achados materiais com regressão reproduzida.
- [ ] **Step 8: atualizar documentação e publicar.** README/guia PT/EN explicam inspeção, prova, consulta e recuperação com erros concretos. Preservar os SVGs de preparação, que ainda descrevem corretamente a missão; ligar diagnóstico pelo guia. Vincular evidências e atualizar YC-201–203 somente pelo aceite atingido. Commit `feat: expose verified mission client checks`; PR protegido, sem bypass, autor humano e memória local atualizada.

## Auto-revisão do plano e encerramento

Cobertura de 2A: configuração/conexão/effort e observação na tarefa 1; processos, limites,
privacidade, idempotência, consumo, timestamp e recuperação na tarefa 2; adoção, CLI, skills,
ambos os clientes/sistemas, matriz e documentação na tarefa 3. Os cinco riscos da seção Review
Focus têm cenários explícitos. Assinaturas consumidas são as do contrato comum.

A cobertura restante da frente 2 está em YC-204–209; QA em YC-301–305; publicação/avisos em
YC-401–405. Os quatro defaults da fundação e os limites já escolhidos pela missão são preservados.
Este plano não altera as respostas aprovadas da entrevista nem cria uma conta de modelo.

Critério para encerrar 2A: mecanismo determinístico verificado em Linux/Windows, recuperação
provada e pelo menos o caminho autenticado de cada cliente comprovado no perfil anunciado.
Células API/ambiente ainda sem acesso permanecem explicitamente pendentes; não podem ser vendidas
como verificadas. Se faltar prova de um cliente padrão, a implementação pode ser publicada como
parcial, mas YC-203 e 2A continuam abertos. Autorizar chamadas não elimina limites nem necessidade
de evidência. A próxima entrega será o plano de 2B, apoiado nesses contratos.

O mantenedor aprovou este plano e esclareceu que modelo e esforço devem vir das opções atuais
do cliente, à escolha do desenvolvedor. `latest` significa recomendação atual da conta;
`native: client-default` mantém o esforço padrão. A liberação dos perfis continua dependente de
prova própria; aprovação da implementação não remove esse gate.
