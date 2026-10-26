# Executar no PowerShell do Windows, na conta que utiliza esta distribuição WSL.
# A tarefa roda diariamente às 08:00 enquanto o usuário estiver conectado.
param(
    [Parameter(Mandatory=$true)][string]$Distribuicao,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Diretorio,
    [string]$Horario = "08:00"
)
$ErrorActionPreference = "Stop"
if ($Distribuicao.Contains('"') -or $Diretorio.Contains('"')) {
    throw 'Distribuição e diretório não podem conter aspas.'
}
if (-not $Diretorio.StartsWith('/')) {
    throw 'Informe em -Diretorio o caminho absoluto do projeto dentro do WSL.'
}
$nome = "CNJ-AtualizarIndicadores"
if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
    throw "A tarefa $nome já existe. Edite-a no Agendador para evitar sobrescrever uma configuração existente."
}
$argumentos = '-d "{0}" --exec bash "{1}/scripts/monitorar_cnj.sh"' -f $Distribuicao, $Diretorio.TrimEnd('/')
$acao = New-ScheduledTaskAction -Execute "wsl.exe" -Argument $argumentos
$gatilho = New-ScheduledTaskTrigger -Daily -At $Horario
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$usuario = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho `
    -Settings $config -Principal $principal -Description "Atualiza os indicadores históricos do CNJ quando houver nova versão."
Write-Host "Tarefa criada. Configure a URL oficial em atualizacao_cnj.json antes da primeira execução."
