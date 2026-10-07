# Execute no PowerShell como o usuário Windows que terá acesso aos arquivos e e-mail.
$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Ambiente virtual não encontrado. Execute instalar.bat primeiro.' }
foreach ($Spec in @(@{Name='THI - Robo Apolices - 06h';Time='06:00'},@{Name='THI - Robo Apolices - 21h';Time='21:00'})) {
  $Action = New-ScheduledTaskAction -Execute $Python -Argument '-m app.main' -WorkingDirectory $Project
  $Trigger = New-ScheduledTaskTrigger -Daily -At $Spec.Time
  $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $Spec.Name -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Executa o robô local de controle de apólices.' -Force | Out-Null
  Write-Host "Tarefa registrada: $($Spec.Name) às $($Spec.Time)"
}
Write-Host 'As tarefas usam a identidade atual. Configure credenciais para essa conta no .env.'
