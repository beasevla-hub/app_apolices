$ErrorActionPreference = 'Stop'
'THI - Robo Apolices - 06h','THI - Robo Apolices - 21h' | ForEach-Object { Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "Removida (se existia): $_" }
