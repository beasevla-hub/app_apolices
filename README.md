# Robô de Controle de Apólices THI / PHAS

Aplicativo local para Windows que consulta a Locaweb por IMAP SSL, classifica PDFs de e-mails da Finlândia Seguros, extrai dados com OpenRouter multimodal e organiza documentos, planilhas e histórico de execução.

> O repositório não contém credenciais. `--test` e os testes automatizados são offline/mockados. `--dry-run` não é um teste offline: ele ainda chama o OpenRouter e consome créditos.

## Instalação e configuração

1. Instale Python 3.12+.
2. Clone/extraia o repositório e execute `instalar.bat`.
3. Preencha `.env` com `EMAIL_USER`, `EMAIL_PASSWORD`, `OPENROUTER_API_KEY`, caminhos e domínios/remetentes permitidos. `.env` não é versionado.
4. Valide com `python -m app.main --test` e `python -m pytest -q`; depois execute o backfill real para o período desejado.

`OPENROUTER_MODEL` continua configurável. O modelo escolhido precisa aceitar PDFs e JSON Schema estrito. `THI_NAMES`/`PHAS_NAMES` definem nomes jurídicos reconhecidos; `THI_CNPJ`/`PHAS_CNPJ` configuram CNPJs para desempate determinístico (o exemplo já traz o CNPJ THI informado). `MAX_EMAILS_PER_RUN` limita a busca diária. `ROBOT_MAX_ATTEMPTS` permanece apenas por compatibilidade/auditoria: tentativas não bloqueiam processamento.

## Comandos

### Teste offline (sem credenciais)

```powershell
python -m app.main --test
python -m pytest -q
```

### Execução diária normal ou análise sem publicação (opcional)

```powershell
python -m app.main
python -m app.main --dry-run
```

O modo normal busca e-mails novos/relevantes. A conclusão é decidida por par: um par `SUCESSO` com os mesmos hashes é ignorado; qualquer par ainda não concluído pode ser tentado novamente. O contador não bloqueia a execução. `--dry-run` conecta ao IMAP/OpenRouter e faz classificação/análises, mas não publica PDFs nem altera o Excel; portanto **consome chamadas/créditos** e não deve ser usado como teste offline nem como execução do backlog.

### Backfill histórico

```powershell
python -m app.main --backfill --inicio 21/09/2026 --fim 07/10/2026
```

Datas usam `DD/MM/AAAA`; ambas as extremidades são inclusivas. A busca IMAP usa `SINCE início` e `BEFORE (fim + 1 dia)`, inclui e-mails lidos, filtra os domínios permitidos e não aplica `UNSEEN` nem `MAX_EMAILS_PER_RUN`. A data inválida ou invertida é rejeitada antes de conectar.

No backfill, status geral do e-mail, estado antigo do grupo e contador de tentativas **nunca bloqueiam**. Cada e-mail é classificado uma vez (salvo cache local); depois de identificar os pares, o único skip é um par já concluído: status `SUCESSO` com os mesmos hashes posicionais de apólice e boleto (e lote compatível quando necessário). `ERRO`, `PROCESSANDO`, `IGNORADO`, estados desconhecidos e tentativas altas são retomados. Em mensagens multilote, cada grupo é decidido independentemente: sucessos são pulados, os demais analisados. `--retry-errors` pode ser omitido; se fornecido com `--backfill`, é apenas um alias compatível, sem lógica própria. Backfill é sempre execução real e não aceita `--dry-run` nem `DRY_RUN=true`.

Uma falha em um grupo ou e-mail não interrompe os demais. Em perda de transporte IMAP, o cliente fecha o socket quebrado, reconecta com espera limitada de 2/4/8 segundos, seleciona novamente a pasta e repete o UID atual. Se os retries se esgotarem, o lote para com **resumo parcial explícito**; sucessos já persistidos continuam registrados e podem ser retomados sem reanálise.

`Ctrl+C` interrompe imediatamente o processamento corrente: não tenta novamente a chamada HTTP interrompida nem avança para o próximo e-mail. O robô tenta persistir o grupo/e-mail como `ERRO`, salva o histórico disponível, preserva grupos já concluídos e encerra com uma mensagem curta (código 130). Uma nova execução do mesmo intervalo retoma o que não concluiu.

Ao final do backfill, o resumo informa mensagens candidatas, remetentes relevantes, resultados, classificações, análises de apólices e total de chamadas. Se não houver remetentes relevantes, informa isso sem falha.

## Classificação por lote e publicação

O robô aceita e-mails com múltiplos pares apólice/boleto, identificadores de lote, documentos `OUTRO` e grupos incompletos. A primeira chamada classifica **todos os PDFs do e-mail** em grupos sem assumir que anexos consecutivos formam pares. Cada grupo referencia os nomes exatos dos arquivos e um identificador de lote com fonte/confiança. Todos os PDFs precisam estar atribuídos a um grupo ou explicitamente listados como `OUTRO`; ambiguidade, duplicidade de arquivo, lote repetido ou par incompleto exige revisão.

Depois, é feita **uma análise multimodal independente por par** (três primeiras páginas da apólice e boleto completo). Além dos campos e evidências, a IA deve confirmar `par_coerente=true` após comparar órgão, concorrência e lote dos dois documentos. O lote da classificação é `lote_associado` (metadado usado em diretórios, Excel e controle); `lote`/`lote_documental` representa somente um identificador explicitamente extraído. O lote documental pode ser `null` mesmo havendo lote associado: nesse caso, o operacional usa o associado sem criar evidência documental. Se ambos existirem, um conflito reprova o par. Sem lote associado, um lote documental continua exigindo evidência e confiança suficientes. Se um par conflitar ou falhar, os demais pares válidos do e-mail ainda podem concluir.

Os documentos são organizados em `RAIZ/THI-ou-PHAS/DD.MM.AAAA/ORGAO - NUMERO/`. Com vários grupos, cada par recebe uma subpasta do lote associado (`LOTE 01`, `LOTE 02`); se lote não for identificado, usa-se um rótulo neutro como `GRUPO 01`, sem inventar identificador. Em qualquer caso, os nomes dos PDFs são curtos e fixos: `01. APOLICE.pdf` e `08. BOLETO.pdf`; órgão, concorrência e lote não se repetem nos nomes. Os nomes e caminhos são construídos pelo Python, não pela IA. Arquivos `OUTRO` não são publicados como apólice/boleto.

A classificação e seu mapa de hashes são armazenados localmente para retomada do mesmo e-mail. O controle grava estado, tentativas, hashes, lote e destino **separadamente para cada par**; a idempotência usa message-id, group-key e os dois hashes, não nomes físicos dos arquivos. As tentativas são auditoria, não uma barreira. Na retomada, grupos já concluídos não voltam a consumir análise; qualquer grupo sem sucesso pode ser processado, inclusive um estado `PROCESSANDO` deixado por encerramento abrupto. Uma eventual diferença de conteúdo em um destino existente causa conflito, sem sobrescrita silenciosa. Registros de sucesso existentes e seus PDFs legados não são renomeados nem apagados: o controle os reconhece pelos hashes; na ausência de registro, o publicador também reconhece um par legado apenas se os dois PDFs corresponderem aos hashes de origem.

## Dados, planilhas e histórico

Os campos estruturados vêm como `{valor, fonte, confianca}`. A IA não deve inventar, completar dígitos ou corrigir valores documentais. A empresa jurídica original é preservada; antes da validação Pydantic, o Python compara o nome com `THI_NAMES`/`PHAS_NAMES` ignorando acentos, caixa, pontuação e sufixos societários finais. CNPJ documental configurado e com confiança suficiente prevalece em caso de conflito. Nome/CNPJ sem correspondência segura deixa `empresa_normalizada` e `tipo_empresa` como `null`, exigindo revisão. A linha digitável é transcrita literalmente; qualquer validação posterior deve ser separada e nunca modificar o original. Dados mínimos, evidências e datas são validados por Python/Pydantic.

O Excel operacional usa exclusivamente a aba `APÓLICES`; sem essa aba, o robô falha sem escolher outra. A correspondência de cabeçalhos tolera ordem/whitespace e sinônimos usuais. A chave é **empresa normalizada + SEI + concorrência + lote** quando há SEI; sem SEI, **empresa + concorrência + órgão + lote**, e só pode recorrer ao órgão quando a linha preexistente também não contém SEI. Um SEI diferente não cai no fallback. Mais de uma correspondência gera `POSSIVEL_DUPLICATA`, sem escrita. Se não houver coluna `LOTE`, uma nova coluna é acrescentada ao final; entradas sem lote mantêm a célula vazia.

São atualizadas somente as colunas gerenciadas pelo robô (incluindo `LOTE`); valores `null` não apagam dados existentes. Para workbooks existentes, são preservados os demais campos, fórmulas, estilos, larguras, filtros, tabelas, freeze panes e linhas manuais. Um backup é criado antes da alteração; o salvamento é temporário/atômico. Se o Excel falhar depois de publicar PDFs novos, o robô tenta removê-los e não grava sucesso daquele grupo.

A publicação valida os comprimentos absolutos da origem, destino, pasta final e temporário; caminhos acima do limite preventivo de 240 caracteres são diagnosticados e rejeitados antes da cópia. Cada origem ainda é revalidada antes da cópia; o robô cria um temporário curto e exclusivo em `data/tmp_publish/`, copia e verifica seu hash, e então o copia ao destino final sem criar temporário dentro da pasta de publicação. O log de falha inclui operação, caminhos absolutos (origem/destino/temporário), existência/acesso, componentes e comprimentos dos caminhos e indícios de pastas sincronizadas (OneDrive/SharePoint/Dropbox/Google Drive, quando detectáveis), além da exceção original. Temporários e PDFs novos da tentativa são removidos após falha; arquivos preexistentes com hash igual são idempotentes e conteúdo diferente nunca é sobrescrito. Um par encontrado com hashes iguais nos nomes legados é mantido no lugar e reconhecido sem renomeação automática.

Cada tentativa cria:

```text
data/historico/<id_processamento>/resultado.json

data/historico/<id_processamento>/metadata.json
```

O metadata registra modo (`NORMAL`, `DRY_RUN` ou `BACKFILL`), message-id/UID, remetente, assunto, modelo, quantidade de PDFs/grupos, lotes, hashes/estados por grupo, issues e timestamp UTC. Respostas de cada par ficam em `lotes/<group_key>/resultado.json`. O mapa reutilizável de classificação fica em `data/historico/classificacoes/`. Dados operacionais, histórico, logs, backups e `.env` são locais e ignorados pelo Git.

## Agendamento Windows

O Task Scheduler é configurado pelos scripts para 06:00 e 21:00. Revise identidade e permissões da conta agendada antes de ativar as tarefas; o robô é uma execução finita, não um daemon.

## Validação antes de operar

```powershell
python -m app.main --test
python -m pytest -q
```

Os dois primeiros comandos são offline e usam validação/mocks; não acessam IMAP nem OpenRouter reais. O comando `python -m app.main --backfill --inicio DD/MM/AAAA --fim DD/MM/AAAA` é execução real: conecta ao IMAP, chama OpenRouter para classificação e para cada grupo ainda não concluído, publica PDFs e atualiza o Excel. Não use `--dry-run` para validar o backlog.

## Troubleshooting

- **IMAP/reconexão:** confirme host, porta SSL, credenciais e `ALLOWED_SENDER_DOMAINS`; se a reconexão limitada esgotar, o resumo indica execução parcial.
- **OpenRouter:** confirme chave, modelo com suporte a PDF/JSON Schema, limites e disponibilidade.
- **Excel bloqueado ou cabeçalho ambíguo:** feche o workbook e revise os nomes na aba `APÓLICES`; a falha não será marcada como sucesso.
- **Conflito ou documento ambíguo:** consulte `logs/robo.log`, metadata, resultado por lote e `data/temp/` quando mantido.
- **Task Scheduler:** confirme usuário, diretório de trabalho, rede e permissões no histórico de tarefas.

O robô não move, apaga ou marca mensagens no servidor e não envia e-mails.
