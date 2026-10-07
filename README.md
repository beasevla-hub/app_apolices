# Robô de Controle de Apólices THI / PHAS

Aplicativo local para Windows que consulta a Locaweb por IMAP SSL, identifica PDFs de e-mails da Finlândia Seguros, classifica e extrai informações com OpenRouter multimodal, gera histórico e organiza os documentos/planilhas.

> Não há credenciais no repositório. O teste offline e todos os testes automatizados usam dados/mocks. O backfill `--dry-run` é a primeira execução recomendada na máquina configurada: conecta aos serviços reais, mas não publica PDFs nem altera o Excel operacional.

## Instalação e configuração

1. Instale Python 3.12+.
2. Clone/extraia o repositório e execute `instalar.bat`.
3. Preencha `.env` com `EMAIL_USER`, `EMAIL_PASSWORD`, `OPENROUTER_API_KEY`, caminhos e remetentes. `.env` não é versionado.
4. Verifique o smoke test offline, depois rode um backfill `--dry-run` para o período histórico desejado.

`OPENROUTER_MODEL` continua configurável. O modelo precisa suportar anexos PDF e JSON Schema estrito. `MAX_EMAILS_PER_RUN` limita apenas a execução diária; `ROBOT_MAX_ATTEMPTS` define o máximo de tentativas por e-mail (padrão 5).

## Comandos

### Teste offline (sem credenciais)

```powershell
python -m app.main --test
python -m pytest -q
```

### Execução diária normal

```powershell
python -m app.main
```

### Dry-run diário

```powershell
python -m app.main --dry-run
```

O dry-run real conecta ao IMAP e OpenRouter, baixa/classifica/análisa e valida, cria `resultado.json` e `metadata.json` e registra `IGNORADO` com nota `DRY_RUN` no controle técnico. Não publica PDFs, não altera `controle_apolices.xlsx` nem grava `SUCESSO`.

### Backfill histórico real

```powershell
python -m app.main --backfill --inicio 01/08/2026 --fim 30/09/2026
```

### Backfill histórico dry-run — recomendado inicialmente

```powershell
python -m app.main --backfill --inicio 01/08/2026 --fim 30/09/2026 --dry-run
```

O backfill serve para carregar o histórico antes de ativar as tarefas diárias. As datas usam `DD/MM/AAAA`; o período é **inclusivo** em ambos os extremos. A busca IMAP usa `SINCE início` e `BEFORE (fim + 1 dia)`, filtra o domínio permitido após a busca e inclui e-mails lidos. Não usa `UNSEEN` nem `MAX_EMAILS_PER_RUN`. O fluxo de cada e-mail é o mesmo `process_message()` da execução normal. Um erro individual é registrado, e o lote segue para as mensagens seguintes. Uma data inválida ou invertida é rejeitada antes de conectar ao IMAP.

Ao final, o resumo informa mensagens candidatas encontradas, remetentes relevantes, sucessos, ignorados/revisão, erros, mensagens sem PDFs válidos, chamadas lógicas OpenRouter e local do histórico. Se nenhum remetente relevante for encontrado, informa isso e encerra sem falha.

## Processamento, IA e histórico

A arquitetura mantém duas chamadas multimodais: (1) classificar os PDFs como APÓLICE/BOLETO/OUTRO; (2) enviar as três primeiras páginas da apólice e o boleto completo para extração estruturada. A temperatura é zero; o JSON Schema é strict. O OpenRouter recebe como referer o repositório GitHub do projeto.

A IA retorna valor, fonte documental e confiança por campo. O Python valida a resposta com Pydantic e constrói nomes/pastas determinísticos. Não interpreta semanticamente PDF, não completa números e não corrige a linha digitável.

Cada análise tem:

```text
data/historico/<id_processamento>/resultado.json
 data/historico/<id_processamento>/metadata.json
```

O metadata inclui modo (`NORMAL`, `DRY_RUN`, `BACKFILL` ou `BACKFILL_DRY_RUN`), message-id/UID, remetente, assunto, modelo, anexos e timestamp. Credenciais não são armazenadas. `data/`, `logs/` e `backups/` estão ignorados pelo Git.

## Idempotência e planilhas

`controle_robo.xlsx`, aba `EMAILS_PROCESSADOS`, mantém identificadores, hashes, estado, tentativas, modelo, datas e destino. Ao iniciar nova tentativa, limpa erro e destino antigos; ao concluir sucesso limpa erro. Mensagens em `SUCESSO` e hashes já processados são ignorados. `ROBOT_MAX_ATTEMPTS` impede reprocessamento infinito.

O Excel operacional usa exclusivamente a aba `APÓLICES`; se um arquivo existente não a possuir, o robô falha sem escolher outra aba. A chave é **empresa normalizada + SEI + concorrência** quando há SEI; sem SEI, **empresa + concorrência + órgão**. Um SEI diferente é outro registro, mesmo que número e órgão coincidam. Múltiplas correspondências geram `POSSIVEL_DUPLICATA`, sem alteração.

São alteradas somente as 10 colunas gerenciadas. Campos `null` preservam valores existentes; colunas manuais, fórmulas, larguras, filtros e tabelas existentes não são reconfigurados. Um backup é criado antes da gravação. O salvamento é temporário/atômico; se o Excel falhar após novos PDFs serem publicados, há tentativa de rollback desses PDFs e não se registra `SUCESSO`.

## Agendamento Windows

O Task Scheduler já está configurado pelos scripts para 06:00 e 21:00; o robô continua sendo uma execução finita, não um daemon. Revise identidade e permissões da conta agendada antes de ativar tarefas.

## Comandos para validar na sua máquina

Depois de configurar credenciais, execute nesta ordem:

```powershell
python -m app.main --test
python -m pytest -q
python -m app.main --backfill --inicio 01/08/2026 --fim 30/09/2026 --dry-run
```

Após revisar histórico/logs e os diagnósticos, rode o backfill real sem `--dry-run`. Depois habilite a execução diária. Não executei nem tentarei conexões reais neste ambiente; o código foi verificado localmente com mocks.

## Troubleshooting

- **IMAP:** confirme host/porta SSL, credenciais e domínio em `ALLOWED_SENDER_DOMAINS`.
- **OpenRouter:** confirme chave, suporte PDF/JSON Schema, limites e nome do modelo.
- **Excel bloqueado:** feche o arquivo operacional; tentativas têm backoff e falha não será marcada como sucesso.
- **Conflito ou erro documental:** consulte `logs/robo.log`, `data/temp/` e o `resultado.json` do histórico.
- **Task Scheduler:** confirme usuário, pasta de trabalho, rede e permissões no histórico de tarefas.

O robô não move, apaga ou marca mensagens no servidor e não envia e-mails.
