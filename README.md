# Robô de Controle de Apólices THI / PHAS

Aplicativo local para Windows que consulta mensagens IMAP SSL da Locaweb, identifica anexos PDF, usa OpenRouter multimodal para classificar e extrair informações com evidências, valida resultados, organiza documentos e atualiza Excel operacional sem sobrescrever campos manuais.

> `.env` não é versionado. Configure credenciais e valide a execução com `--dry-run` (que conecta ao IMAP e OpenRouter, mas não publica nem altera o Excel) antes de ativar o agendamento.

## Arquitetura

`app.main` busca mensagens e delega cada uma a `process_message()`. Os módulos mantêm responsabilidades separadas:

- `email_client`: IMAP SSL por UID, busca mensagens recentes sem depender de `UNSEEN`, valida domínio do endereço do remetente e baixa anexos.
- `attachment_processor` / `pdf_processor`: valida PDFs, exige exatamente um papel APÓLICE e BOLETO e gera PDF temporário somente com as três primeiras páginas da apólice.
- `openrouter_client` / `prompt`: duas chamadas multimodais OpenRouter com JSON Schema e temperatura zero: (1) classificação dos anexos; (2) análise das páginas iniciais da apólice + boleto completo.
- `models` / `validator`: Pydantic valida estrutura, datas, empresa THI/PHAS, vigência e evidências/confiança por campo.
- `file_manager`: gera caminho e nomes finais determinísticos no Python, sanitiza caracteres Windows, verifica SHA-256 e não sobrescreve arquivo conflitante.
- `excel_apolices`: atualiza somente colunas gerenciadas na aba `APÓLICES`, preserva colunas manuais e faz backup antes de gravação atômica.
- `excel_robot_control`: estados, hashes, tentativas, modelo e ID da execução.

## Instalação no Windows

1. Instale Python 3.12+ (marque “Add Python to PATH”).
2. Clone/extraia o repositório em diretório local permanente.
3. Execute `instalar.bat`.
4. Edite `.env` (criado a partir de `.env.example`) para fornecer IMAP, OpenRouter e caminhos.
5. Execute `python -m app.main --test`, depois `executar_dry_run.bat` com credenciais reais configuradas.

As tarefas usam a identidade Windows que as registra; essa identidade deve acessar `.env`, mailbox e pastas compartilhadas.

## Configuração

Preencha `EMAIL_USER`, `EMAIL_PASSWORD`, `OPENROUTER_API_KEY`; confirme `PASTA_RAIZ`, `CONTROLE_APOLICES`, remetentes e nomes empresariais. `OPENROUTER_MODEL` continua configurável; o modelo deve aceitar PDFs e JSON Schema. `MAX_EMAILS_PER_RUN` controla a janela de mensagens mais recentes. `ROBOT_MAX_ATTEMPTS` limita reprocessamentos (padrão 5). `DRY_RUN=true` ativa simulação real; não é um substituto para credenciais. Nunca coloque segredo em arquivo versionado.

## Execução

```powershell
.venv\Scripts\python.exe -m app.main --test
.venv\Scripts\python.exe -m app.main --dry-run
.venv\Scripts\python.exe -m app.main
```

- `--test`: offline, sem IMAP/OpenRouter/Excel operacional.
- `--dry-run`: conecta ao IMAP, baixa PDFs, classifica, analisa e valida; guarda diagnóstico/histórico e atualiza estado técnico como `IGNORADO` com indicação de dry-run; não publica PDFs, não altera Excel operacional nem registra sucesso definitivo. Exige credenciais IMAP e OpenRouter.
- Sem argumento: fluxo normal com publicação, Excel e controle `SUCESSO`.
- Testes locais: `.venv\Scripts\python.exe -m pytest -q`.

## Extração, evidência e confiança

A resposta inclui, para os campos prioritários, `{valor, fonte, confianca}`. Fontes permitidas: `APOLICE`, `BOLETO`, `AMBOS`, `NAO_IDENTIFICADO`. Valores ausentes ou ilegíveis devem vir como null; conflitos e campos incertos devem constar em `campos_com_duvida`/`observacoes`. O prompt proíbe completar trechos, inferir dados ou corrigir dígitos da linha digitável. Os campos usados para publicação precisam confiança mínima de 0,75. Se dados mínimos ou confiança forem insuficientes, nenhuma publicação é feita e os temporários permanecem para revisão.

`empresa_normalizada` é a chave empresarial autorizada (`THI`/`PHAS`), não uma inferência textual do Python. O nome jurídico da IA pode ser escrito no Excel. A IA sugere nomes, mas os definitivos são construídos programaticamente a partir do órgão e número normalizados.

## Excel e idempotência

`controle_apolices.xlsx` deve usar a aba `APÓLICES`; se o arquivo já existe sem essa aba, o robô falha conservadoramente sem escolher a aba ativa. O arquivo novo recebe a aba e cabeçalhos. São gerenciadas apenas dez colunas declaradas em `ROBOT_MANAGED_COLUMNS`; colunas manuais não são limpas ou sobrescritas. Um valor novo `null` preserva valor existente. Atualizações usam chave empresa normalizada + SEI + concorrência; sem SEI, empresa + concorrência + órgão. Múltiplas correspondências provocam `POSSIVEL_DUPLICATA` e nenhuma alteração.

Antes da atualização, cria backup em `backups/controle_apolices_YYYYMMDD_HHMMSS_*.xlsx`. A gravação usa arquivo temporário, validação e substituição atômica. Erros de bloqueio fazem tentativas com backoff finito; em falha, há rollback dos PDFs novos e não há `SUCESSO`.

`controle_robo.xlsx` (aba `EMAILS_PROCESSADOS`) mantém message-id/UID, hashes da apólice e boleto, status (`PROCESSANDO`, `SUCESSO`, `ERRO`, `IGNORADO`), tentativas, modelo, timestamps, erro, destino e `id_processamento`. Um registro que ficou em `PROCESSANDO` pode ser retomado na próxima execução enquanto estiver dentro do limite configurado; após o limite permanece para revisão. Mensagens concluídas são ignoradas. SHA-256 reduz reanálise de documentos já processados.

## Histórico e arquivos locais

Cada tentativa cria `data/historico/<id_processamento>/resultado.json` (resposta estruturada exata da IA) e `metadata.json` (identificação da mensagem, modelo e anexos, sem credenciais). Os PDFs temporários ficam em `data/temp/` durante execução/erro; em sucesso podem ser apagados, conforme `KEEP_SUCCESS_TEMP`. `data/`, `logs/` e `backups/` ficam fora do Git.

## Task Scheduler

Execute `./instalar_tarefa_windows.ps1` no PowerShell para criar tarefas diárias às 06:00 e 21:00, sem daemon contínuo. Para remover, `./remover_tarefas_windows.ps1`. Revise usuário, autenticação e permissões no Task Scheduler.

## Troubleshooting

- IMAP: valide host/porta SSL, senha, acesso e `ALLOWED_SENDER_DOMAINS`.
- OpenRouter HTTP 400/401/402/429 ou 500: confira modelo, JSON Schema, suporte PDF, credenciais e limites; há retries limitados e nenhum segredo é escrito nos logs.
- Excel bloqueado: feche o arquivo operacional; as tentativas têm backoff e a execução não será marcada como sucesso se persistir.
- Documento incompleto, conflito ou duplicata: consulte `logs/robo.log`, a pasta temporária e o histórico `resultado.json` para revisão.
- Task Scheduler: confira o histórico da tarefa, diretório de trabalho e conta de execução.

O robô não move nem apaga mensagens no servidor e não envia e-mails. Uma rodada sem mensagens novas não chama o OpenRouter.
