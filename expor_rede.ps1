# Expõe os dashboards do WSL para a rede local.
# Rodar no PowerShell do Windows COMO ADMINISTRADOR.
# Precisa ser rodado de novo sempre que o WSL reiniciar (o IP interno muda).

$portas = 8050, 8052, 8053

$ipWsl = (wsl.exe -e hostname -I).Trim().Split(" ")[0]
# Pega o adaptador que tem o gateway padrão — filtrar só por prefixo 192.168.*
# pegaria o adaptador host-only do VirtualBox (192.168.56.1), não o Wi-Fi.
$ipLan = (Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
    Select-Object -First 1).IPv4Address.IPAddress

Write-Host "IP do WSL: $ipWsl"
Write-Host "IP da LAN: $ipLan`n"

# Firewall: uma regra por porta, criada só se ainda não existir.
foreach ($p in $portas) {
    if (-not (Get-NetFirewallRule -DisplayName "Dash $p" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "Dash $p" -Direction Inbound `
            -Action Allow -Protocol TCP -LocalPort $p | Out-Null
        Write-Host "Regra de firewall criada para a porta $p"
    }
}

function Set-Proxy($escuta) {
    foreach ($p in $portas) {
        # Limpa as duas variantes de listenaddress antes de recriar.
        netsh interface portproxy delete v4tov4 listenport=$p listenaddress=0.0.0.0 2>$null | Out-Null
        netsh interface portproxy delete v4tov4 listenport=$p listenaddress=$ipLan 2>$null | Out-Null
        netsh interface portproxy add v4tov4 listenport=$p listenaddress=$escuta `
            connectport=$p connectaddress=$ipWsl
    }
    # O iphlpsvc é quem de fato encaminha. Depois de mexer nas regras ele costuma
    # ficar escutando na porta sem repassar (sintoma: timeout, não "recusado").
    Restart-Service iphlpsvc -Force
    Start-Sleep -Seconds 4
}

function Test-Portas {
    $ok = $true
    foreach ($p in $portas) {
        try {
            $r = Invoke-WebRequest "http://${ipLan}:$p/" -TimeoutSec 8 -UseBasicParsing
            Write-Host "  http://${ipLan}:$p  ->  OK ($($r.StatusCode))" -ForegroundColor Green
        } catch {
            Write-Host "  http://${ipLan}:$p  ->  FALHOU" -ForegroundColor Red
            $ok = $false
        }
    }
    return $ok
}

Write-Host "`n[1/2] Tentando escutar em 0.0.0.0..." -ForegroundColor Cyan
Set-Proxy "0.0.0.0"
if (Test-Portas) {
    Write-Host "`nPronto. Acesse pelos endereços acima." -ForegroundColor Green
    netsh interface portproxy show v4tov4
    exit 0
}

# 0.0.0.0 às vezes não encaminha; amarrar no IP da placa costuma resolver.
Write-Host "`n[2/2] Nao funcionou. Tentando escutar em $ipLan..." -ForegroundColor Cyan
Set-Proxy $ipLan
if (Test-Portas) {
    Write-Host "`nPronto. Acesse pelos endereços acima." -ForegroundColor Green
} else {
    Write-Host "`nAs duas tentativas falharam. Mande esta saida para o Claude." -ForegroundColor Yellow
}

netsh interface portproxy show v4tov4
