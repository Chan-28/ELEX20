$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'python-embed\python.exe'
$requirements = Join-Path $projectRoot 'requirements.txt'
$wheelDir = Join-Path $projectRoot 'third_party\wheels'

if (-not (Test-Path $pythonExe)) {
    throw "Python embutido nao encontrado em: $pythonExe"
}

if (-not (Test-Path $requirements)) {
    throw "Arquivo requirements.txt nao encontrado em: $requirements"
}

New-Item -ItemType Directory -Path $wheelDir -Force | Out-Null

Write-Host 'Baixando wheels Python para instalacao offline...'
& $pythonExe -m pip download -r "$requirements" --only-binary=:all: --dest "$wheelDir"
if ($LASTEXITCODE -ne 0) {
    throw 'Falha ao baixar wheels para modo offline.'
}

Write-Host "Wheels salvas em: $wheelDir"
