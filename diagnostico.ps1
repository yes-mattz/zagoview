# Zagoview - relatorio de diagnostico
#
# Levanta o que o Windows e o VISA enxergam nesta maquina e grava tudo num
# arquivo de texto na Area de Trabalho, para ser enviado a quem der suporte.
#
# Nao precisa de Python, nem de privilegio de administrador, e nao altera
# nada: todas as consultas sao de leitura.
#
# Para rodar, abra o PowerShell nesta pasta e execute:
#     powershell -ExecutionPolicy Bypass -File diagnostico.ps1

$saida = Join-Path ([Environment]::GetFolderPath('Desktop')) `
                   "zagoview-diagnostico-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
$linhas = New-Object System.Collections.ArrayList

function Escrever($texto) {
    [void]$linhas.Add($texto)
    Write-Host $texto
}

function Secao($titulo) {
    Escrever ""
    Escrever ("=" * 70)
    Escrever "  $titulo"
    Escrever ("=" * 70)
}

function Tentar($rotulo, $bloco) {
    try { & $bloco }
    catch { Escrever "  [falhou: $rotulo] $($_.Exception.Message)" }
}

Secao "IDENTIFICACAO"
Escrever "  data/hora : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"
Tentar "computador" {
    $c = Get-CimInstance Win32_ComputerSystem
    $o = Get-CimInstance Win32_OperatingSystem
    Escrever "  maquina   : $($c.Manufacturer) $($c.Model)"
    Escrever "  windows   : $($o.Caption) $($o.Version)"
    Escrever "  usuario   : $env:USERNAME  (admin: $(
        (New-Object Security.Principal.WindowsPrincipal(
            [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)))"
}

Secao "1. INSTRUMENTOS USB QUE O WINDOWS ENXERGA"
Escrever "  VID_0699=Tektronix  VID_2A8D=Keysight  VID_1AB1=Rigol  VID_0AAD=R&S"
Tentar "dispositivos USB" {
    $d = Get-PnpDevice | Where-Object {
        $_.Class -eq 'USBTestAndMeasurementDevice' -or
        $_.InstanceId -match 'VID_0699|VID_2A8D|VID_1AB1|VID_0AAD|VID_0957'
    }
    if (-not $d) {
        Escrever "  NENHUM instrumento USB conhecido encontrado."
    } else {
        foreach ($i in $d) {
            Escrever "  presente=$($i.Present)  status=$($i.Status)"
            Escrever "     nome  : $($i.FriendlyName)"
            Escrever "     classe: $($i.Class)"
            Escrever "     id    : $($i.InstanceId)"
        }
    }
}
Escrever ""
Escrever "  -- dispositivos USB com problema (qualquer fabricante) --"
Tentar "dispositivos com erro" {
    $p = Get-CimInstance Win32_PnPEntity |
         Where-Object { $_.ConfigManagerErrorCode -ne 0 -and $_.DeviceID -match '^USB' }
    if (-not $p) { Escrever "     nenhum" }
    else { foreach ($i in $p) {
        Escrever "     erro=$($i.ConfigManagerErrorCode)  $($i.Name)"
        Escrever "        $($i.DeviceID)"
    } }
}

Secao "2. PORTAS SERIAIS (COM)"
Escrever "  O Zagoview lista portas COM como ASRL<n>::INSTR. Se o instrumento"
Escrever "  estiver ligado por cabo serial, ele aparece aqui."
Tentar "portas COM" {
    $portas = [System.IO.Ports.SerialPort]::GetPortNames()
    if (-not $portas) { Escrever "  nenhuma porta COM nesta maquina." }
    else {
        Escrever "  portas: $($portas -join ', ')"
        Escrever ""
        Escrever "  -- o que esta por tras de cada uma --"
        Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue | ForEach-Object {
            Escrever "     presente=$($_.Present)  $($_.FriendlyName)"
            Escrever "        $($_.InstanceId)"
        }
    }
}

Secao "3. IMPLEMENTACOES VISA INSTALADAS"
Tentar "programas VISA" {
    $ch = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    $v = Get-ItemProperty $ch -ErrorAction SilentlyContinue |
         Where-Object { $_.DisplayName -match 'VISA|IO Libraries|TekVISA|NI-VISA' } |
         Select-Object DisplayName, DisplayVersion, Publisher | Sort-Object DisplayName
    if (-not $v) { Escrever "  NENHUMA implementacao VISA encontrada." }
    else { foreach ($i in $v) {
        Escrever "  $($i.DisplayName)  v$($i.DisplayVersion)  [$($i.Publisher)]"
    } }
}
Escrever ""
Escrever "  -- bibliotecas VISA no sistema --"
Tentar "dlls VISA" {
    $achou = $false
    foreach ($f in Get-ChildItem 'C:\Windows\System32\*visa*.dll' -ErrorAction SilentlyContinue) {
        $achou = $true
        Escrever "     $($f.Name)  [$($f.VersionInfo.CompanyName)] v$($f.VersionInfo.FileVersion)"
    }
    if (-not $achou) { Escrever "     NENHUMA - sem VISA o programa nao fala com instrumento algum." }
}

Secao "4. O QUE O VISA ENXERGA"
$recursos = @()
Escrever "  -- tentativa 1: interface COM do VISA --"
Tentar "VISA-COM" {
    $rm = New-Object -ComObject VISA.GlobalRM
    $achados = $rm.FindRsrc("?*")
    if ($achados) {
        $recursos = @($achados)
        foreach ($r in $achados) { Escrever "     $r" }
    } else { Escrever "     nenhum recurso encontrado" }
}

Escrever ""
Escrever "  -- tentativa 2: Python + pyvisa (se existir nesta maquina) --"
Tentar "python" {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { Escrever "     Python nao instalado - normal, o executavel nao precisa dele." }
    else {
        Escrever "     python em: $py"
        $script = @'
import time
try:
    import pyvisa
except ImportError:
    print("     pyvisa nao instalado"); raise SystemExit
try:
    rm = pyvisa.ResourceManager()
except Exception as e:
    print("     nao abriu o VISA:", type(e).__name__, e); raise SystemExit
print("     biblioteca:", rm.visalib)
achados = list(rm.list_resources())
print("     recursos  :", achados or "nenhum")
for r in achados:
    try:
        inst = rm.open_resource(r)
        inst.timeout = 3000
        t0 = time.time()
        idn = inst.query("*IDN?").strip()
        print(f"       {r} -> {time.time()-t0:.2f}s -> {idn!r}")
        inst.close()
    except Exception as e:
        print(f"       {r} -> {type(e).__name__}: {str(e).splitlines()[0]}")
'@
        $tmp = Join-Path $env:TEMP "zv_diag.py"
        Set-Content -Path $tmp -Value $script -Encoding UTF8
        & $py $tmp 2>&1 | ForEach-Object { Escrever "  $_" }
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

Secao "5. PORTAS SERIAIS: TENTATIVA DE CONVERSA"
Escrever "  Uma porta serial nao delimita mensagens sozinha: e preciso acertar"
Escrever "  a velocidade e o caractere de fim de linha. Aqui testamos as"
Escrever "  combinacoes mais comuns, mandando *IDN? em cada uma."
Tentar "sondagem serial" {
    $portas = [System.IO.Ports.SerialPort]::GetPortNames()
    if (-not $portas) { Escrever "  nenhuma porta COM para testar." }
    foreach ($porta in $portas) {
        Escrever ""
        Escrever "  ---- $porta ----"
        foreach ($baud in 9600, 19200, 38400, 57600, 115200) {
            foreach ($fim in @{n = "LF";   v = "`n"},
                             @{n = "CRLF"; v = "`r`n"}) {
                $sp = $null
                try {
                    $sp = New-Object System.IO.Ports.SerialPort $porta, $baud, 'None', 8, 'One'
                    $sp.ReadTimeout = 1500
                    $sp.WriteTimeout = 1500
                    $sp.Open()
                    $sp.DiscardInBuffer()
                    $sp.Write("*IDN?" + $fim.v)
                    Start-Sleep -Milliseconds 400
                    $resp = ""
                    if ($sp.BytesToRead -gt 0) { $resp = $sp.ReadExisting() }
                    $resp = $resp -replace "[`r`n]", " "
                    if ($resp.Trim()) {
                        Escrever "     $baud $($fim.n.PadRight(4)) -> RESPONDEU: $($resp.Trim())"
                    } else {
                        Escrever "     $baud $($fim.n.PadRight(4)) -> silencio"
                    }
                } catch {
                    Escrever "     $baud $($fim.n.PadRight(4)) -> $($_.Exception.Message.Split([char]10)[0])"
                } finally {
                    if ($sp -and $sp.IsOpen) { $sp.Close() }
                    if ($sp) { $sp.Dispose() }
                }
            }
        }
    }
}

Secao "6. QUAL ZAGOVIEW ESTA NESTA MAQUINA"
Tentar "executavel" {
    $locais = @("$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop",
                "$env:USERPROFILE\Documents", $PSScriptRoot)
    $achou = $false
    foreach ($l in $locais) {
        Get-ChildItem $l -Filter 'Zagoview.exe' -Recurse -Depth 2 `
            -ErrorAction SilentlyContinue | ForEach-Object {
            $achou = $true
            Escrever "  $($_.FullName)"
            Escrever "     $([math]::Round($_.Length/1MB,1)) MB   $($_.LastWriteTime)"
            try {
                Escrever "     sha256: $((Get-FileHash $_.FullName -Algorithm SHA256).Hash)"
            } catch {
                Escrever "     sha256: NAO FOI POSSIVEL LER - provavelmente bloqueado pelo antivirus"
            }
        }
    }
    if (-not $achou) { Escrever "  nenhum Zagoview.exe encontrado nos locais usuais." }
}

Secao "FIM"
Escrever "  Relatorio salvo em:"
Escrever "  $saida"

$linhas | Out-File -FilePath $saida -Encoding UTF8
Write-Host ""
Write-Host "Pronto. Envie o arquivo:" -ForegroundColor Green
Write-Host "  $saida" -ForegroundColor Green
exit 0
