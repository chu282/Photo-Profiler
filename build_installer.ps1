$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& (Join-Path $PSScriptRoot 'build_portable.ps1')
$compilerPath = Join-Path $PSScriptRoot '.temp\inno\ISCC.exe'
if (-not (Test-Path -LiteralPath $compilerPath)) {
    throw 'Extract the Inno Setup compiler into .temp\inno before building the installer.'
}
& $compilerPath '/Qp' (Join-Path $PSScriptRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
