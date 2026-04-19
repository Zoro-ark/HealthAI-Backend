$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
  throw "Backend virtual environment not found at $python"
}

Push-Location $root
try {
  & $python -m uvicorn ml_service.main:app --host 0.0.0.0 --port 8000 --reload
} finally {
  Pop-Location
}
