$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'python-embed\python.exe'
$getPip = Join-Path $projectRoot 'get-pip.py'
$requirements = Join-Path $projectRoot 'requirements.txt'
$wheelDir = Join-Path $projectRoot 'third_party\wheels'

if (-not (Test-Path $pythonExe)) {
    throw "Python embutido nao encontrado em: $pythonExe"
}

if (-not (Test-Path $requirements)) {
    throw "Arquivo requirements.txt nao encontrado em: $requirements"
}

Write-Host '[1/4] Validando pip no python-embed...'
$hasPip = $true
try {
    & $pythonExe -m pip --version | Out-Null
    if ($LASTEXITCODE -ne 0) { $hasPip = $false }
} catch {
    $hasPip = $false
}

if (-not $hasPip) {
    if (-not (Test-Path $getPip)) {
        throw "get-pip.py nao encontrado em: $getPip"
    }
    Write-Host '[2/4] Instalando pip local...'
    & $pythonExe $getPip
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha ao instalar pip no python-embed.'
    }
}

Write-Host '[3/4] Instalando dependencias Python no python-embed...'
function Install-Requirements([string]$reqPath, [bool]$offlineMode) {
    if ($offlineMode) {
        & $pythonExe -m pip install --no-index --find-links "$wheelDir" -r "$reqPath" 2>&1 | Out-Host
    } else {
        & $pythonExe -m pip install -r "$reqPath" 2>&1 | Out-Host
    }
    return [int]$LASTEXITCODE
}

if ((Test-Path $wheelDir) -and ((Get-ChildItem -Path $wheelDir -Filter '*.whl' -ErrorAction SilentlyContinue).Count -gt 0)) {
    Write-Host 'Modo offline: usando third_party/wheels'
    $installCode = Install-Requirements -reqPath $requirements -offlineMode $true
} else {
    Write-Host 'Modo online: baixando do indice padrao (sem wheel cache local).'
    $installCode = Install-Requirements -reqPath $requirements -offlineMode $false
}

if ($installCode -ne 0) {
    Write-Warning 'Falha ao instalar todas as dependencias. Tentando modo sem rpy2...'

    $tmpReq = Join-Path $projectRoot 'requirements_no_rpy2.txt'
    Get-Content $requirements |
        Where-Object { $_ -notmatch '^\s*rpy2' } |
        Set-Content -Path $tmpReq -Encoding UTF8

    if ((Test-Path $wheelDir) -and ((Get-ChildItem -Path $wheelDir -Filter '*.whl' -ErrorAction SilentlyContinue).Count -gt 0)) {
        $installCode = Install-Requirements -reqPath $tmpReq -offlineMode $true
    } else {
        $installCode = Install-Requirements -reqPath $tmpReq -offlineMode $false
    }

    Remove-Item $tmpReq -ErrorAction SilentlyContinue

    if ($installCode -ne 0) {
        throw 'Falha na instalacao das dependencias Python (inclusive modo sem rpy2).'
    }

    Write-Warning 'Dependencias instaladas sem rpy2. Os graficos em R podem nao funcionar neste Python; fallback Python permanecera ativo.'
}

$sentinel = Join-Path $projectRoot '.deps_python_ok'
Set-Content -Path $sentinel -Value (Get-Date).ToString('s') -Encoding UTF8
Write-Host '[4/4] Dependencias Python instaladas com sucesso.'
