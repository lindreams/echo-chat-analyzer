param([Parameter(Mandatory=$true)][string]$BuildRoot)
$ErrorActionPreference = 'Stop'
$Source = $PSScriptRoot
$Repo = (Resolve-Path (Join-Path $Source '../../..')).Path
$Output = [IO.Path]::GetFullPath($BuildRoot)
if (-not $Output.StartsWith((Join-Path $Repo 'build') + '\', [StringComparison]::OrdinalIgnoreCase) -or $Output.Contains('"')) {
    throw 'BuildRoot must be inside this checkout build directory'
}
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$Deps = Join-Path $Output 'minhook'
$Pins = Get-Content (Join-Path $Source 'minhook-pins.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($Entry in $Pins.files.PSObject.Properties) {
    $Target = Join-Path $Deps $Entry.Name
    if (-not (Test-Path -LiteralPath $Target)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri ('https://raw.githubusercontent.com/TsudaKageyu/minhook/' + $Pins.revision + '/' + $Entry.Name) -OutFile $Target
    }
    if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Entry.Value) { throw 'MinHook source hash mismatch' }
}
$Vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$VS = & $Vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $VS) { throw 'Existing MSVC x64 toolchain required; no automatic installation' }
$Vcvars = Join-Path $VS 'VC/Auxiliary/Build/vcvars64.bat'
function Compile([string[]]$Commands) {
    $Batch = Join-Path $Output 'compile.cmd'
    $Lines = @('@echo off', ('call "' + $Vcvars + '" >nul'), 'if errorlevel 1 exit /b %errorlevel%')
    foreach ($Command in $Commands) { $Lines += $Command; $Lines += 'if errorlevel 1 exit /b %errorlevel%' }
    [IO.File]::WriteAllLines($Batch, $Lines, [Text.Encoding]::ASCII)
    Push-Location $Output
    try { & cmd.exe /d /c $Batch; if ($LASTEXITCODE -ne 0) { throw 'Native compilation failed' } }
    finally { Pop-Location }
}
$HostExe = Join-Path $Output 'echo_qq_event_host.exe'
Compile @('cl /nologo /std:c++17 /EHsc /Od /MD /W4 /Fe:"' + $HostExe + '" /Fo:host.obj "' + (Join-Path $Source 'host.cpp') + '" /link /INCREMENTAL:NO /DYNAMICBASE /NXCOMPAT')
$HostHash = (Get-FileHash -LiteralPath $HostExe -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $Output 'fixture_identity.h'), ('inline constexpr char echo_fixture_hash[] = "' + $HostHash + '";'), [Text.Encoding]::ASCII)
$Includes = '/I"' + (Join-Path $Deps 'include') + '" /I"' + $Output + '"'
$CFiles = @('src/buffer.c','src/hook.c','src/trampoline.c','src/hde/hde64.c') | ForEach-Object { '"' + (Join-Path $Deps $_) + '"' }
Compile @('cl /nologo /c /O2 /MD ' + $Includes + ' ' + ($CFiles -join ' '))
$AdapterSource = Join-Path $Source 'adapter.cpp'
Compile @(
    ('cl /nologo /std:c++17 /EHsc /O2 /MD /W4 /LD ' + $Includes + ' /DECHO_FIXTURE_BUILD /Fo:adapter_fixture.obj /Fe:echo_event_fixture.dll "' + $AdapterSource + '" buffer.obj hook.obj trampoline.obj hde64.obj bcrypt.lib /link /INCREMENTAL:NO /DYNAMICBASE /NXCOMPAT'),
    ('cl /nologo /std:c++17 /EHsc /O2 /MD /W4 /LD ' + $Includes + ' /Fo:adapter_54395.obj /Fe:echo_event_54395.dll "' + $AdapterSource + '" buffer.obj hook.obj trampoline.obj hde64.obj bcrypt.lib /link /INCREMENTAL:NO /DYNAMICBASE /NXCOMPAT')
)
Copy-Item -LiteralPath (Join-Path $Deps 'LICENSE.txt') -Destination (Join-Path $Output 'MinHook.LICENSE.txt')
$Receipt = [ordered]@{ minhook_revision=$Pins.revision; build='9.9.37-54395'; binaries=[ordered]@{} }
foreach ($Name in @('echo_qq_event_host.exe','echo_event_fixture.dll','echo_event_54395.dll')) {
    $Receipt.binaries[$Name] = (Get-FileHash -LiteralPath (Join-Path $Output $Name) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$Receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Output 'build-receipt.json') -Encoding UTF8
Write-Output 'Built owned fixture host and both adapter variants; no QQ process accessed.'
