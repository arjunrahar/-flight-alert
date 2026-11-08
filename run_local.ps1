# Runs one price check on this PC using settings from .env (copy .env.example to .env first).
Set-Location $PSScriptRoot
if (Test-Path .env) {
  Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $v = ($v -split '#')[0].Trim()
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, 'Process')
  }
}
python check_prices.py 2>&1 | Tee-Object -FilePath last_run.log
