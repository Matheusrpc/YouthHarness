# Diagnóstico limitado dos clientes

Frente: 2A, executor e adaptadores; YC-201–203. Entrega parcial. A fila de PBIs,
QA e publicação autônomos permanecem nas próximas frentes do [backlog](../BACKLOG.md).

O desenvolvedor escolhe modelo e esforço pelo catálogo da conta. `latest` seleciona a
recomendação do cliente naquele instante; um nome explícito fixa a escolha. `client-default`
omite a substituição de esforço. Nenhuma dessas opções permite trocar de conexão ou
reduzir o esforço silenciosamente. A configuração global continua podendo ser alterada
por missão. O diagnóstico não torna a missão executável.

## Implementação e evidência

- `client inspect`: versão, hash do executável, catálogo, esforços e tipo de login oficial.
- `client check`: manifesto autorizado, nonce fixo, reserva durável antes do processo,
  prazo e saída limitados, encerramento da árvore própria e recibo privado.
- `client runs` e `status`: consulta sem escrita, migração ou chamada de modelo.
- `client reconcile`: referências privadas por hash, confirmação de término e revisão
  explícita do efeito externo; conserva tentativas e reservas.

O esquema SQLite 2 é aditivo e transacional. As notas ficam em
`vault/local/missions/<mission-uuid>/runs/`, com microíndice e vínculo à missão.
Saída bruta e credenciais não entram nos recibos. Uma falha ao projetar o Markdown
não repete o fornecedor. Edições humanas geram conflito preservado.

Os testes determinísticos usam processos reais e um cliente fictício sem rede.
Cobrem queda antes/depois do efeito, repetição do UUID, migração abortada, conflito
de revisão, reserva de limites, timeout com descendente e preservação de processo
alheio. A prova de adoção usa a CLI instalada em consumidores novo e existente,
passando por instalação, execução, consulta, recuperação e retorno.

Resultados consolidados e comandos ficam em
[mission-runtime-adapters.json](../medicoes/mission-runtime-adapters.json).
Os primeiros 69 testes de missões passaram no Windows em 848,731 segundos,
com um skip exclusivo de Linux. Casos adicionais de recuperação e limite foram
incluídos depois dessa corrida e têm medição separada.

## Matriz nativa

| Célula | Evidência | Estado |
|---|---|---|
| Codex 0.146.0, Windows, assinatura | Catálogo e status de login oficiais; ensaio local do perfil ainda anunciou `view_image` | Execução bloqueada; nenhum turno real enviado |
| Claude Code 2.1.220, Windows, assinatura | Catálogo e login oficiais; ensaio local anunciou ferramentas, MCPs, skills e plugins vazios | Execução bloqueada: precedência das políticas gerenciadas ainda sem prova; nenhum turno real enviado |
| Codex/Claude, Linux x86-64 | Supervisão e recuperação determinísticas no CI; cliente fictício | Perfil nativo não comprovado; execução bloqueada |
| API explícita, ambos | Contrato de configuração e recusas determinísticas | Indisponível: orçamento/precedência ainda sem prova completa |
| macOS e outras arquiteturas | Sem prova de contenção | Indisponível |

O ensaio de perfil aponta os clientes para um servidor HTTP local, sem credencial
real e sem cobrança. Ele examina o catálogo efetivo de ferramentas; não substitui
a conversa nativa. Codex continuou oferecendo `view_image` mesmo com
`tools.view_image=false`; `view_image_tool` foi recusada como flag desconhecida.
O diagnóstico desse binário fica bloqueado. Novos modelos não exigem alterar uma
lista fixa no código; versões/binários novos exigem prova do perfil de permissões.

O executável Claude usado no ensaio tem o hash
`af5bf1f1b2aadffc768eccd787084c6fdf9ba81624cbe96c1c6d9ac1a1550231`.
A documentação do modo seguro mantém certas políticas gerenciadas ativas. A prova
local com ferramentas vazias não certifica essa precedência em outras instalações;
por isso nenhum perfil de produção foi liberado nesta entrega.
Receber `latest` não baixa um cliente nem confirma o lançamento global mais recente.
No catálogo inspecionado, as recomendações foram `gpt-5.6-sol` e `claude-opus-5[1m]`;
esses nomes são observações, não defaults gravados no harness.

## Limites e decisões de implementação

Um diagnóstico pode confirmar apenas sua própria combinação de cliente, conta,
modelo, esforço e perfil. `runnable` e `runtime_available` continuam falsos.
Reservas anteriores contam no limite mesmo quando a execução falha. Custo ausente
continua nulo; custo informado pelo cliente não prova cobrança de assinatura.

Windows atribui um Job Object antes de liberar o cliente e encerra seus descendentes
quando o coordenador cai. Linux x86-64 herda um filtro que impede sair do grupo de
processos; um watchdog encerra o grupo após perda do coordenador. Esses mecanismos
controlam a vida dos processos, sem constituir isolamento de arquivos ou rede.
Permissões do modelo dependem de um perfil nativo comprovado.

O setup conserva os três helpers novos quando já existem, inclusive com `--force`.
Instalações mistas exigem comparação manual; incompatibilidades detectadas bloqueiam
a operação. As skills `yc-config` e `yc-status` foram exercitadas em contextos
independentes antes/depois da edição, sem executar modelos externos no diagnóstico.

Decisões tomadas durante a execução do plano:

- Reusar o checkout exclusivo e manter um escritor; risco se incorreto: interferência.
- Acrescentar Git Bash somente ao PATH dos testes; risco: diferença em outros ambientes.
- A pergunta inicial de modelo ficou pendente até a resposta do mantenedor; sem resposta,
  as provas nativas ficariam abertas. Sua resposta autorizou catálogo dinâmico e `latest`.
- Interpretar `latest` como recomendação atual da conta; risco: ela pode atrasar um lançamento.
- Usar cinco segundos no teste de descendente Windows, pois um segundo expirava durante
  o bootstrap; risco: teste mais lento. O prazo de produto permanece configurável.
- Admitir `client-default` para modelos sem controle de esforço; risco: o padrão muda
  no fornecedor, por isso o esforço observado não é inventado.
- Dar 30 segundos à fixture de execução e ao Git local e 180 segundos ao novo teste
  de instalação, após timeouts de infraestrutura; risco: testes mais lentos. Os limites
  do executor não mudaram.
- Começar a ligação da CLI enquanto a regressão do executor rodava; risco: integração
  prematura, coberta pela corrida instalada e pela revisão final.
- Usar um caminho curto fora do Git para a prova de retorno Windows; o caminho longo
  em Temp foi recusado pelo contrato de adoção, sem alterar essa proteção.
- Manter ambos os perfis nativos bloqueados após a conferência das políticas gerenciadas;
  risco: a chamada real permanece indisponível até uma prova adicional. A autorização
  do mantenedor não substitui a comprovação dos limites exigidos pelo plano.

## Fontes consultadas

O catálogo segue o contrato nativo de [model/list do Codex](https://learn.chatgpt.com/docs/app-server).
As flags foram conferidas na [referência do Claude Code](https://code.claude.com/docs/en/cli-reference)
e na [configuração do Codex](https://learn.chatgpt.com/docs/config-file/config-reference), junto
da ajuda dos executáveis instalados. A divergência do Codex foi medida localmente.
A supervisão usa [Job Objects do Windows](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
e [seccomp do Linux](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html).
O limite do modo seguro consta nas [variáveis do Claude](https://code.claude.com/docs/en/env-vars)
e no contrato de [políticas gerenciadas](https://code.claude.com/docs/en/managed-settings).
As fontes ingeridas por Docling ficam no vault privado com origem e revisão.

2A e YC-203 continuam abertos até comprovar o caminho autenticado de cada cliente.
O próximo gate é fechar essa matriz; 2B depende dele.
