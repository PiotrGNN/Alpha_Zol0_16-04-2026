$ErrorActionPreference = 'Stop'
$python = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { throw 'Python is required.' }
& $python -m tools.zol0ctl @args
exit $LASTEXITCODE
