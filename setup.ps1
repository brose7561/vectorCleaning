# Windows PowerShell: install uv if missing, then create .venv and install deps.
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv sync
if (-not (Get-Command potrace -ErrorAction SilentlyContinue)) {
    Write-Host "note: 'scoop install potrace' for trace.py's best backend"
}
Write-Host "ready -> uv run clean.py --help"
