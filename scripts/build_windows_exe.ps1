param(
    [string]$ProjectRootOverride = "",
    [string]$MsvcRuntimeDirectoryOverride = "",
    [switch]$RuntimeOnly,
    [string]$DistPathOverride = "",
    [string]$WorkPathOverride = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = if ($ProjectRootOverride) {
    [System.IO.Path]::GetFullPath($ProjectRootOverride)
}
else {
    Split-Path -Parent $PSScriptRoot
}
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
$RuntimeSource = Join-Path $ProjectRoot "runtime"
$DistRoot = if ($DistPathOverride) { [IO.Path]::GetFullPath($DistPathOverride) } else { Join-Path $ProjectRoot "dist" }
$PortableDirectory = Join-Path $DistRoot "Echo"
if ($DistPathOverride -and (Test-Path -LiteralPath $DistRoot)) {
    throw 'An overridden dist directory must be new; existing artifacts are never replaced.'
}
$PortableRuntime = Join-Path $PortableDirectory "runtime"
$MsvcRuntimeNames = @(
    "msvcp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll"
)
$MsvcRuntimeTargets = @("qq-napcat-candidate", "wechat")
$MsvcRuntimeMinimumVersion = [Version]"14.43"

# The portable runtime contract lives in one tracked manifest so the build and
# the tests can never drift into two hand-maintained required-asset lists.
# It sits next to this script and also pins the machine-local state that must
# never ship, so it is resolved from the script location rather than from the
# (possibly overridden) project root.
$RuntimeContractPath = Join-Path $PSScriptRoot "windows_runtime_manifest.json"
$RuntimeContract = $null
$QQConfigSeeds = @()

function Get-RuntimeContract {
    if ($null -ne $RuntimeContract) {
        return $RuntimeContract
    }
    if (-not (Test-Path -LiteralPath $RuntimeContractPath -PathType Leaf)) {
        throw "Runtime contract manifest is missing: scripts\windows_runtime_manifest.json"
    }
    $Contract = (
        Get-Content -LiteralPath $RuntimeContractPath -Raw -Encoding UTF8
    ) | ConvertFrom-Json
    if (-not $Contract.requirements -or -not $Contract.privatePaths -or
        -not $Contract.packageDirectories -or -not $Contract.releaseTreePrivatePaths -or
        -not $Contract.wechatPinnedAssets -or -not $Contract.portableExcludedFiles -or
        -not $Contract.releaseCopyrightFiles) {
        throw "Runtime contract manifest is incomplete: scripts\windows_runtime_manifest.json"
    }
    $script:RuntimeContract = $Contract
    return $script:RuntimeContract
}

function Get-QQConfigSeedRequirement {
    return @(
        (Get-RuntimeContract).requirements | Where-Object {
            [string]$_.source -eq "qq-napcat-candidate" -and
            ([string]$_.path) -like "qq-napcat-candidate/config/*" -and
            [string]$_.type -eq "file"
        }
    )
}

function Test-PortableExcludedFile([string]$RelativePath) {
    # Exact runtime-relative file paths only; source validation never uses this.
    return $RelativePath -in (Get-RuntimeContract).portableExcludedFiles
}

function Assert-NapCatArtifactPins([string]$Root, [string]$Phase) {
    $PinsName = [string](Get-RuntimeContract).qqPins
    if ($PinsName -ne 'qq_napcat_runtime_pins.json') {
        throw 'Release must use the official Echo NapCat pins.'
    }
    $Pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot $PinsName) -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Pins.upstream.version -ne '4.18.34' -or $Pins.upstream.project -ne 'NapNeko/NapCatQQ') {
        throw 'Unsupported release NapCat source.'
    }
    $Hashes = @{}
    foreach ($Property in $Pins.requiredFiles.PSObject.Properties) {
        $Hashes[$Property.Name] = [string]$Property.Value
    }
    $Hashes[[string]$Pins.napcatPatch.path] = [string]$Pins.napcatPatch.patchedSha256
    $Hashes['config/plugins.json'] = [string]$Pins.pluginConfigSha256
    foreach ($Template in $Pins.templates) {
        $Hashes[[string]$Template.target] = [string]$Template.sha256
    }
    foreach ($Name in $Hashes.Keys) {
        if ($Name -match '(^/|\\|:|(^|/)\.\.(/|$))' -or $Hashes[$Name] -notmatch '^[0-9a-f]{64}$') {
            throw 'Invalid NapCat artifact pin.'
        }
        if ($Phase -eq 'portable' -and (Test-PortableExcludedFile ("qq-napcat-candidate/" + $Name))) {
            continue
        }
        $Target = Join-Path $Root ("qq-napcat-candidate/" + $Name)
        Assert-ProgramPathNotLinked $Target
        if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Hashes[$Name]) {
            throw ('NapCat artifact pin mismatch: ' + $Name)
        }
    }
}

function Assert-WeChatArtifactPins([string]$Root) {
    # Record the identity of the exact native WeChat binaries that ship. This is
    # deliberately not build attestation: the WCDB library and its helper are
    # local builds whose PE timestamps make bit-for-bit rebuilds impossible, so
    # the hash freezes which build is released, and a swap or a partial copy
    # fails instead of silently shipping a different binary.
    $Pins = (Get-RuntimeContract).wechatPinnedAssets
    foreach ($Property in $Pins.PSObject.Properties) {
        $Name = [string]$Property.Name
        $Hash = ([string]$Property.Value).ToLowerInvariant()
        if ($Name -match '(^/|\\|:|(^|/)\.\.(/|$))' -or $Hash -notmatch '^[0-9a-f]{64}$') {
            throw 'Invalid WeChat artifact pin.'
        }
        $Target = Join-Path $Root ($Name -replace '/', '\')
        if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
            throw ('Pinned WeChat asset is missing: ' + $Name)
        }
        Assert-ProgramPathNotLinked $Target
        if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Hash) {
            throw ('WeChat artifact pin mismatch: ' + $Name)
        }
    }
}

function Assert-ReleaseTreeStateAbsent([string]$Root) {
    # The app writes ``logs`` beside its own executable, and the bundled WeChat
    # diagnostic runner writes its report next to itself. A fresh build produces
    # neither, so their presence means a previous local run leaked into the tree
    # that is about to be handed to users.
    foreach ($Relative in (Get-RuntimeContract).releaseTreePrivatePaths) {
        $RelativePath = ([string]$Relative) -replace '/', '\'
        if (Test-Path -LiteralPath (Join-Path $Root $RelativePath)) {
            throw (
                'Release tree contains state that must never ship: ' +
                [string]$Relative +
                '. Run a full build (not -RuntimeOnly) and do not launch the ' +
                'packaged app before packaging.'
            )
        }
    }
}

function Assert-ReleaseCopyrightFiles([string]$Root) {
    foreach ($Relative in (Get-RuntimeContract).releaseCopyrightFiles) {
        if ($Relative -match '(^/|\\|:|(^|/)\.\.(/|$))') {
            throw 'Invalid release copyright file path.'
        }
        $Target = Join-Path $Root $Relative
        if (-not (Test-Path -LiteralPath $Target -PathType Leaf) -or
            (Get-Item -LiteralPath $Target).Length -eq 0) {
            throw ('Required release copyright file is missing or empty: ' + $Relative)
        }
        Assert-ProgramPathNotLinked $Target
    }
}

function Assert-RuntimeContract {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [ValidateSet("source", "portable")]
        [string]$Phase
    )

    $MissingMessage = if ($Phase -eq "source") {
        "Required runtime resource is missing"
    }
    else {
        "Portable runtime copy is incomplete"
    }
    $EmptyMessage = if ($Phase -eq "source") {
        "Required runtime directory is empty"
    }
    else {
        "Portable runtime directory is empty"
    }

    foreach ($Requirement in (Get-RuntimeContract).requirements) {
        if ($Phase -eq 'portable' -and (Test-PortableExcludedFile ([string]$Requirement.path))) {
            continue
        }
        $RelativePath = ([string]$Requirement.path) -replace '/', '\'
        $Target = Join-Path $Root $RelativePath
        switch ([string]$Requirement.type) {
            "file" {
                if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
                    throw ($MissingMessage + ": runtime\" + $RelativePath)
                }
            }
            "non-empty-directory" {
                if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
                    throw ($MissingMessage + ": runtime\" + $RelativePath)
                }
                if (@(Get-ChildItem -LiteralPath $Target -Force).Count -eq 0) {
                    throw ($EmptyMessage + ": runtime\" + $RelativePath)
                }
            }
            default {
                throw (
                    "Unknown runtime contract requirement type '" +
                    [string]$Requirement.type + "': runtime\" + $RelativePath
                )
            }
        }
    }
    Assert-NapCatArtifactPins $Root $Phase
    Assert-WeChatArtifactPins $Root
    if ($Phase -eq 'portable') {
        foreach ($Relative in (Get-RuntimeContract).portableExcludedFiles) {
            if (Test-Path -LiteralPath (Join-Path $Root $Relative)) {
                throw ('Excluded portable runtime asset: ' + $Relative)
            }
        }
        foreach ($Relative in (Get-RuntimeContract).forbiddenPaths) {
            if (Test-Path -LiteralPath (Join-Path $Root $Relative)) {
                throw ('Forbidden release runtime asset: ' + $Relative)
            }
        }
    }
}

function Assert-PrivateRuntimeStateAbsent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    foreach ($Entry in (Get-RuntimeContract).privatePaths) {
        $RelativePath = ([string]$Entry.path) -replace '/', '\'
        $Target = Join-Path $Root $RelativePath
        if (Test-Path -LiteralPath $Target) {
            throw ($Label + ": runtime\" + $RelativePath)
        }
    }
}

function Test-MutableRuntimePath([string]$RelativePath) {
    # One policy for state accidentally placed inside an allowed program tree.
    # Static auth/sessions folders are frontend routes, not user state.
    $Parts = $RelativePath.ToLowerInvariant() -split '/'
    $Directories = @('output', 'logs', 'cache', 'temp', 'tmp', 'staging',
        'generations', 'decrypted', 'scratch', 'data', 'reports', '.codex',
        'session', 'sessions', 'auth')
    for ($Index = 0; $Index -lt $Parts.Count - 1; $Index++) {
        if ($Parts[$Index] -in $Directories) {
            return $true
        }
    }
    $Name = $Parts[-1]
    return ($Name -match '\.(?:db(?:-(?:wal|shm|journal))?|sqlite(?:3)?|jsonl|log)$' -or
        $Name -eq '.env' -or
        $Name -match '^(?:token|key|cookie|password|passphrase|credentials|security|session|auth|account)(?:[._-].*)?\.(?:json|txt|ini|env)$')
}

function Assert-ProgramPathNotLinked([string]$Path) {
    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if ((Get-Item -LiteralPath $Current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Runtime program asset is a reparse point; refusing to package it.'
        }
        $Parent = Split-Path -Parent $Current
        if ($Parent -eq $Current) { break }
        $Current = $Parent
    }
}

function Copy-RuntimeProgramAssets([string]$SourceRoot, [string]$DestinationRoot) {
    # requirements is a presence contract, not permission to copy broad roots
    # such as qq/plugins. Only its explicit files and packageDirectories ship.
    $Files = @{}
    $Contract = Get-RuntimeContract
    foreach ($Entry in @($Contract.requirements | Where-Object { $_.type -eq 'file' }) +
        @($Contract.packageDirectories)) {
        $Relative = [string]$Entry.path
        if ($Relative -match '(^|/)(qce-server\.exe|napcat-plugin-qce)(/|$)|(^|/)static/qce(/|$)') {
            throw 'QCE is not a release program asset.'
        }
        if ($Relative -match '(^/|\\|:|(^|/)\.\.(/|$))' -or
            -not $Relative.StartsWith(([string]$Entry.source + '/'))) {
            throw 'Invalid runtime program asset path in manifest.'
        }
        $Source = Join-Path $SourceRoot $Relative
        Assert-ProgramPathNotLinked $Source
        if ([string]$Entry.type -eq 'file') {
            if (Test-MutableRuntimePath $Relative) { throw 'Manifest names a mutable runtime asset.' }
            $Files[$Relative] = $Source
        }
        elseif ([string]$Entry.type -eq 'directory') {
            $Pending = [Collections.Generic.Stack[string]]::new()
            $Pending.Push($Source)
            while ($Pending.Count) {
                foreach ($Child in Get-ChildItem -LiteralPath $Pending.Pop() -Force) {
                    if ($Child.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        throw 'Runtime program asset is a reparse point; refusing to package it.'
                    }
                    $ChildRelative = $Child.FullName.Substring($SourceRoot.Length + 1) -replace '\\', '/'
                    $PolicyPath = if ($Child.PSIsContainer) { $ChildRelative + '/entry' } else { $ChildRelative }
                    if (Test-MutableRuntimePath $PolicyPath) { continue }
                    if ($Child.PSIsContainer) { $Pending.Push($Child.FullName) }
                    else { $Files[$ChildRelative] = $Child.FullName }
                }
            }
        }
        else { throw 'Invalid runtime program asset type in manifest.' }
    }
    # Enumerate and validate before copying; never visit the live output tree.
    foreach ($Relative in $Files.Keys) {
        if (Test-PortableExcludedFile $Relative) { continue }
        $Destination = Join-Path $DestinationRoot $Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
        Copy-Item -LiteralPath $Files[$Relative] -Destination $Destination
    }
}

if (-not (Test-Path -LiteralPath $RuntimeSource -PathType Container)) {
    throw "Runtime source directory is missing. Restore the repository runtime directory before building."
}

# Validate the contract before packaging starts: a package that would be
# missing a product dependency must never be produced.
Assert-RuntimeContract -Root $RuntimeSource -Phase "source"
Assert-ReleaseCopyrightFiles $ProjectRoot
$QQConfigSeeds = Get-QQConfigSeedRequirement

Push-Location $ProjectRoot
try {
    if (-not $RuntimeOnly) {
        if (-not (Test-Path -LiteralPath $PyInstaller)) {
            throw "Project .venv PyInstaller is missing; restore the approved build environment first."
        }
        $BuildArguments = @('--clean', '--noconfirm', '--distpath', $DistRoot)
        if ($WorkPathOverride) { $BuildArguments += @('--workpath', [IO.Path]::GetFullPath($WorkPathOverride)) }
        & $PyInstaller @BuildArguments LocalChatAnalyzer.spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed with exit code $LASTEXITCODE"
        }
    }

    # Includes RuntimeOnly: copying runtime assets cannot bless an old Python
    # SQLite DLL. The spec pins the input; verify the collected output as well.
    & $VenvPython (Join-Path $PSScriptRoot 'bootstrap_sqlite_runtime.py') --verify (Join-Path $PortableDirectory '_internal/sqlite3.dll')
    if ($LASTEXITCODE -ne 0) {
        throw 'Frozen SQLite DLL failed its release pin; a full rebuild is required.'
    }

    New-Item -ItemType Directory -Force -Path $PortableDirectory | Out-Null
    if (Test-Path -LiteralPath $PortableRuntime) {
        Remove-Item -LiteralPath $PortableRuntime -Recurse -Force
    }
    Copy-RuntimeProgramAssets -SourceRoot $RuntimeSource -DestinationRoot $PortableRuntime

    # Source stays complete; only the exact portableExcludedFiles are omitted.

    # The QQ launchers and WeChat native libraries use the MSVC dynamic
    # runtime. Ship it app-local so both child-process trees also start on
    # clean Windows systems without a separately installed redistributable.
    $WindowsSystemDirectory = if ($MsvcRuntimeDirectoryOverride) {
        [System.IO.Path]::GetFullPath($MsvcRuntimeDirectoryOverride)
    }
    else {
        [Environment]::GetFolderPath("System")
    }
    foreach ($RuntimeName in $MsvcRuntimeNames) {
        $RuntimeDependency = Join-Path $WindowsSystemDirectory $RuntimeName
        if (-not (Test-Path -LiteralPath $RuntimeDependency -PathType Leaf)) {
            throw "Required native runtime dependency is missing: $RuntimeName"
        }
        $RuntimeVersionText = (
            Get-Item -LiteralPath $RuntimeDependency
        ).VersionInfo.FileVersion
        $RuntimeVersion = $null
        if (-not [Version]::TryParse($RuntimeVersionText, [ref]$RuntimeVersion)) {
            throw "Cannot determine native runtime version: $RuntimeName"
        }
        if ($RuntimeVersion -lt $MsvcRuntimeMinimumVersion) {
            throw "Native runtime dependency is too old: $RuntimeName"
        }
        foreach ($RuntimeTarget in $MsvcRuntimeTargets) {
            Copy-Item -LiteralPath $RuntimeDependency -Destination (
                Join-Path $PortableRuntime "$RuntimeTarget\$RuntimeName"
            ) -Force
        }
    }

    # Never publish machine-specific NapCat state, account config, or logs.
    foreach ($GeneratedName in @("cache", "config", "logs")) {
        $GeneratedPath = Join-Path $PortableRuntime "qq-napcat-candidate\$GeneratedName"
        if (Test-Path -LiteralPath $GeneratedPath) {
            Remove-Item -LiteralPath $GeneratedPath -Recurse -Force
        }
    }

    # loadNapCat.js is rewritten by the launcher on every start and embeds the
    # absolute runtime folder of whichever machine generated it.
    $GeneratedLoader = Join-Path $PortableRuntime "qq-napcat-candidate\loadNapCat.js"
    if (Test-Path -LiteralPath $GeneratedLoader) {
        Remove-Item -LiteralPath $GeneratedLoader -Force
    }

    # Restore only the machine-independent config files the contract requires.
    # Everything else under qq\config stays excluded, so a purge followed by an
    # explicit re-copy can never leak a saved path or a per-install file.
    foreach ($Seed in $QQConfigSeeds) {
        $SeedRelativePath = ([string]$Seed.path) -replace '/', '\'
        $SeedDestination = Join-Path $PortableRuntime $SeedRelativePath
        New-Item -ItemType Directory -Force -Path (
            Split-Path -Parent $SeedDestination
        ) | Out-Null
        Copy-Item -LiteralPath (
            Join-Path $RuntimeSource $SeedRelativePath
        ) -Destination $SeedDestination -Force
    }

    Assert-RuntimeContract -Root $PortableRuntime -Phase "portable"
    Assert-PrivateRuntimeStateAbsent -Root $PortableRuntime -Label (
        "Portable runtime contains state that must never ship"
    )
    foreach ($RuntimeName in $MsvcRuntimeNames) {
        foreach ($RuntimeTarget in $MsvcRuntimeTargets) {
            $CopiedDependency = Join-Path (
                $PortableRuntime
            ) "$RuntimeTarget\$RuntimeName"
            if (-not (Test-Path -LiteralPath $CopiedDependency -PathType Leaf)) {
                throw "Portable runtime copy is incomplete: runtime\$RuntimeTarget\$RuntimeName"
            }
        }
    }

    # Ship the WeChat WCDB diagnostic runner so test machines do not have to
    # copy it manually. The frozen app looks for scripts/run_wechat_wcdb_diagnostic.ps1.
    $DiagnosticRunnerSource = Join-Path $ProjectRoot "scripts\run_wechat_wcdb_diagnostic.ps1"
    if (-not (Test-Path -LiteralPath $DiagnosticRunnerSource)) {
        throw "Required diagnostic runner is missing: scripts\run_wechat_wcdb_diagnostic.ps1"
    }
    $PortableScripts = Join-Path $PortableDirectory "scripts"
    New-Item -ItemType Directory -Force -Path $PortableScripts | Out-Null
    Copy-Item -LiteralPath $DiagnosticRunnerSource -Destination (
        Join-Path $PortableScripts "run_wechat_wcdb_diagnostic.ps1"
    )

    foreach ($Relative in (Get-RuntimeContract).releaseCopyrightFiles) {
        $Destination = Join-Path $PortableDirectory $Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
        Copy-Item -LiteralPath (Join-Path $ProjectRoot $Relative) -Destination $Destination
    }
    Assert-ReleaseCopyrightFiles $PortableDirectory

    # The release tree is now complete, so this is the last point where a local
    # run residue could still be caught before the tree is packaged.
    Assert-ReleaseTreeStateAbsent -Root $PortableDirectory

    Write-Output "Build complete: $PortableDirectory"
}
finally {
    Pop-Location
}
