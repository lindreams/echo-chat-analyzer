param(
    [string]$PackageDirectory = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
$PackageDirectory = [IO.Path]::GetFullPath($PackageDirectory)
$AppDirectory = Join-Path $PackageDirectory 'Echo'
$Executable = Join-Path $AppDirectory 'Echo.exe'
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw 'Extract the acceptance ZIP here first. Expected: Echo\Echo.exe'
}

# QQ/Electron needs a coherent Windows profile. Independent directories for
# HOME, USERPROFILE and AppData can stall startup before QR generation.
$ProfileDirectory = Join-Path $PackageDirectory 'acceptance-user\profile'
$LocalDirectory = Join-Path $ProfileDirectory 'AppData\Local'
$Directories = @{
    HOME = $ProfileDirectory
    USERPROFILE = $ProfileDirectory
    APPDATA = Join-Path $ProfileDirectory 'AppData\Roaming'
    LOCALAPPDATA = $LocalDirectory
    TEMP = Join-Path $LocalDirectory 'Temp'
    TMP = Join-Path $LocalDirectory 'Temp'
}
foreach ($Name in $Directories.Keys) {
    $Directory = $Directories[$Name]
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    [Environment]::SetEnvironmentVariable($Name, $Directory, 'Process')
}
foreach ($Name in @('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP')) {
    [Environment]::SetEnvironmentVariable($Name, $null, 'Process')
}
# Interactive GUI only. Connecting QQ and scanning remain explicit user actions.
Start-Process -FilePath $Executable -WorkingDirectory $AppDirectory
