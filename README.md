# Robô de Controle de Apólices THI / PHAS

Aplicativo local para Windows que consulta a Locaweb por IMAP SSL, classifica PDFs de e-mails da Finlândia Seguros, extrai dados com OpenRouter multimodal e organiza documentos, planilhas e histórico de execução.

> O repositório não contém credenciais. O smoke test e os testes automatizados usam dados e serviços mockados. Recomenda-se fazer um backfill com `--dry-run` antes de publicar documentos reais.

## Instalação e configuração

1. Instale Python 3.12+.
2. Clone/extraia o repositório e execute `instalar.bat`.
3. Preencha `.env` com `EMAIL_USER`, `EMAIL_PASSWORD`, `OPENROUTER_API_KEY`, caminhos e domínios/remetentes permitidos. `.env` não é versionado.
4. Execute o smoke test offline, depois um backfill com `--dry-run` para o período desejado.

`OPENROUTER_MODEL` continua configurável. O modelo escolhido precisa aceitar PDFs e JSON Schema estrito. `THI_NAMES`/`PHAS_NAMES` definem nomes jurídicos reconhecidos; `THI_CNPJ`/`PHAS_CNPJ` configuram CNPJs para desempate determinístico (o exemplo já traz o CNPJ THI informado). `MAX_EMAILS_PER_RUN` limita a busca diária; `ROBOT_MAX_ATTEMPTS` define o limite de tentativas por e-mail e por grupo documental (padrão 5).

## Comandos

### Teste offline (sem credenciais)

```powershell
python -m app.main --test
python -m pytest -q
```

### Execução diária normal ou dry-run

```powershell
python -m app.main
python -m app.main --dry-run
```

O dry-run conecta ao IMAP/OpenRouter e processa a classificação e as análises, mas não publica PDFs nem altera o Excel operacional. Ele salva `resultado.json` e `metadata.json` e registra `IGNORADO` com nota `DRY_RUN` no controle técnico.

### Backfill histórico

```powershell
python -m app.main --backfill --inicio 01/08/2026 --fim 30/09/2026
python -m app.main --backfill --inicio 01/08/2026 --fim 30/09/2026 --dry-run
python -m app.main --backfill --inicio 21/09/2026 --fim 07/10/2026 --retry-errors
```

Datas usam `DD/MM/AAAA`; ambas as extremidades são inclusivas. A busca IMAP usa `SINCE início` e `BEFORE (fim + 1 dia)`, inclui e-mails lidos, filtra os domínios permitidos e não aplica `UNSEEN` nem `MAX_EMAILS_PER_RUN`. A data inválida ou invertida é rejeitada antes de conectar.

`--retry-errors` só pode ser combinado com `--backfill`. É uma opção explícita para reprocessar registros com status `ERRO` após correções do robô, mesmo quando já atingiram `ROBOT_MAX_ATTEMPTS`. Não altera o contador histórico: cada nova tentativa o incrementa. Registros `SUCESSO` continuam ignorados e `IGNORADO` não é convertido em erro nem reprocessado por essa opção. Em e-mails multilote, o override é aplicado por `group_key`: grupos `SUCESSO` são pulados, somente grupos `ERRO` podem ser retomados. A classificação existente é reutilizada quando os hashes dos PDFs coincidem; não há nova chamada de classificação nesse caso. Sem `--retry-errors`, o limite normal permanece inalterado.

Uma falha em um grupo ou e-mail não interrompe os demais. Em perda de transporte IMAP, o cliente fecha o socket quebrado, reconecta com espera limitada de 2/4/8 segundos, seleciona novamente a pasta e repete o UID atual. Se os retries se esgotarem, o lote para com **resumo parcial explícito**; sucessos já persistidos continuam registrados e podem ser retomados sem reanálise.

Ao final do backfill, o resumo informa mensagens candidatas, remetentes relevantes, resultados, classificações, análises de apólices e total de chamadas. Se não houver remetentes relevantes, informa isso sem falha.

## Classificação por lote e publicação

O robô aceita e-mails com múltiplos pares apólice/boleto, identificadores de lote, documentos `OUTRO` e grupos incompletos. A primeira chamada classifica **todos os PDFs do e-mail** em grupos sem assumir que anexos consecutivos formam pares. Cada grupo referencia os nomes exatos dos arquivos e um identificador de lote com fonte/confiança. Todos os PDFs precisam estar atribuídos a um grupo ou explicitamente listados como `OUTRO`; ambiguidade, duplicidade de arquivo, lote repetido ou par incompleto exige revisão.

Depois, é feita **uma análise multimodal independente por par** (três primeiras páginas da apólice e boleto completo). Além dos campos e evidências, a IA deve confirmar `par_coerente=true` após comparar órgão, concorrência e lote dos dois documentos. O lote da classificação é `lote_associado` (metadado usado em diretórios, nomes, Excel e controle); `lote`/`lote_documental` representa somente um identificador explicitamente extraído. O lote documental pode ser `null` mesmo havendo lote associado: nesse caso, o operacional usa o associado sem criar evidência documental. Se ambos existirem, um conflito reprova o par. Sem lote associado, um lote documental continua exigindo evidência e confiança suficientes. Se um par conflitar ou falhar, os demais pares válidos do e-mail ainda podem concluir.

Com apenas um grupo, a estrutura de pastas e os nomes anteriores são preservados. Com vários grupos, cada par recebe uma subpasta de lote e os nomes dos dois PDFs recebem o mesmo sufixo (`LOTE 01`, por exemplo), usando o lote associado mesmo quando a apólice não o imprime. Se nem a classificação nem a análise identificarem lote, usa-se um rótulo neutro como `GRUPO 01`; o identificador nunca é inventado. Os nomes e caminhos são construídos pelo Python, não pela IA. Arquivos `OUTRO` não são publicados como apólice/boleto.

A classificação e seu mapa de hashes são armazenados localmente para uma retomada do mesmo e-mail. O controle grava estado, tentativas, hashes, lote e destino **separadamente para cada par**. Checkpoints de `PROCESSANDO` por grupo e chamadas/cache também ficam no metadata. Na retomada, grupos já concluídos não voltam a consumir análise; grupos com erro são reprocessados até o limite configurado. Uma eventual diferença de conteúdo em um destino existente causa conflito, sem sobrescrita silenciosa.

## Dados, planilhas e histórico

Os campos estruturados vêm como `{valor, fonte, confianca}`. A IA não deve inventar, completar dígitos ou corrigir valores documentais. A empresa jurídica original é preservada; antes da validação Pydantic, o Python compara o nome com `THI_NAMES`/`PHAS_NAMES` ignorando acentos, caixa, pontuação e sufixos societários finais. CNPJ documental configurado e com confiança suficiente prevalece em caso de conflito. Nome/CNPJ sem correspondência segura deixa `empresa_normalizada` e `tipo_empresa` como `null`, exigindo revisão. A linha digitável é transcrita literalmente; qualquer validação posterior deve ser separada e nunca modificar o original. Dados mínimos, evidências e datas são validados por Python/Pydantic.

O Excel operacional usa exclusivamente a aba `APÓLICES`; sem essa aba, o robô falha sem escolher outra. A correspondência de cabeçalhos tolera ordem/whitespace e sinônimos usuais. A chave é **empresa normalizada + SEI + concorrência + lote** quando há SEI; sem SEI, **empresa + concorrência + órgão + lote**, e só pode recorrer ao órgão quando a linha preexistente também não contém SEI. Um SEI diferente não cai no fallback. Mais de uma correspondência gera `POSSIVEL_DUPLICATA`, sem escrita. Se não houver coluna `LOTE`, uma nova coluna é acrescentada ao final; entradas sem lote mantêm a célula vazia.

São atualizadas somente as colunas gerenciadas pelo robô (incluindo `LOTE`); valores `null` não apagam dados existentes. Para workbooks existentes, são preservados os demais campos, fórmulas, estilos, larguras, filtros, tabelas, freeze panes e linhas manuais. Um backup é criado antes da alteração; o salvamento é temporário/atômico. Se o Excel falhar depois de publicar PDFs novos, o robô tenta removê-los e não grava sucesso daquele grupo.

Cada tentativa cria:

```text
data/historico/<id_processamento>/resultado.json

data/historico/<id_processamento>/metadata.json
```

O metadata registra modo (`NORMAL`, `DRY_RUN`, `BACKFILL` ou `BACKFILL_DRY_RUN`), message-id/UID, remetente, assunto, modelo, quantidade de PDFs/grupos, lotes, hashes/estados por grupo, issues e timestamp UTC. Respostas de cada par ficam em `lotes/<group_key>/resultado.json`. O mapa reutilizável de classificação fica em `data/historico/classificacoes/`. Dados operacionais, histórico, logs, backups e `.env` são locais e ignorados pelo Git.

## Agendamento Windows

O Task Scheduler é configurado pelos scripts para 06:00 e 21:00. Revise identidade e permissões da conta agendada antes de ativar as tarefas; o robô é uma execução finita, não um daemon.

## Validação antes de operar

```powershell
python -m app.main --test
python -m pytest -q
python -m app.main --backfill --inicio 01/08/2026 --fim 30/09/2026 --dry-run
```

Revise resultados, logs e issues do dry-run antes do backfill real. Este ambiente valida localmente com mocks; não acessa IMAP nem OpenRouter reais.

## Troubleshooting

- **IMAP/reconexão:** confirme host, porta SSL, credenciais e `ALLOWED_SENDER_DOMAINS`; se a reconexão limitada esgotar, o resumo indica execução parcial.
- **OpenRouter:** confirme chave, modelo com suporte a PDF/JSON Schema, limites e disponibilidade.
- **Excel bloqueado ou cabeçalho ambíguo:** feche o workbook e revise os nomes na aba `APÓLICES`; a falha não será marcada como sucesso.
- **Conflito ou documento ambíguo:** consulte `logs/robo.log`, metadata, resultado por lote e `data/temp/` quando mantido.
- **Task Scheduler:** confirme usuário, diretório de trabalho, rede e permissões no histórico de tarefas.

O robô não move, apaga ou marca mensagens no servidor e não envia e-mails.
