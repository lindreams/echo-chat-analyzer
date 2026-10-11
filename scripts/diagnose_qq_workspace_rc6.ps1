# RC6-only, metadata-only. Windows PowerShell 5.1; no elevation, Python or modules.
# No filesystem writes, content reads, process launches, network or business calls.
# Close Echo normally before running; concurrent directory replacement is unverified.
param([string]$ReleaseDirectory = '')

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:Failed = $false
$Component = '61c2be90548a0a77080c9099731e24dcb1ad50790f530ad5ad06ef4cc996c019'

function Emit([string]$Stage, [string]$Code, [bool]$Ok, [bool]$Verified,
    [ValidateSet('workspace_root', 'plugin_container', 'echo_plugin', 'other')][string]$LocationCategory = 'other',
    [ValidateSet('file', 'directory', 'other')][string]$MemberKind = 'other') {
    if (-not $Ok) { $script:Failed = $true }
    $record = [ordered]@{stage=$Stage; code=$Code; ok=$Ok; verified=$Verified}
    if ($Code -ceq 'member_unknown') {
        $record['location_category'] = $LocationCategory
        $record['member_kind'] = $MemberKind
    }
    [Console]::WriteLine(($record | ConvertTo-Json -Compress))
}

# GetFileAttributes via .NET returns attributes of the link itself. Check every
# ancestor before inspecting a descendant; never use Resolve-Path or recursion.
function Get-Metadata([string]$Path, [string]$Stage) {
    try {
        $attributes = [IO.File]::GetAttributes($Path)
        if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Emit $Stage 'reparse_point' $false $true
            return 'blocked'
        }
        if (($attributes -band [IO.FileAttributes]::Directory) -ne 0) { return 'directory' }
        if (($attributes -band [IO.FileAttributes]::Device) -ne 0) {
            Emit $Stage 'member_kind_invalid' $false $true
            return 'blocked'
        }
        return 'file'
    } catch {
        $errorObject = $_.Exception
        while ($null -ne $errorObject.InnerException) { $errorObject = $errorObject.InnerException }
        if ($errorObject -is [IO.FileNotFoundException] -or $errorObject -is [IO.DirectoryNotFoundException]) { return 'missing' }
        Emit $Stage 'metadata_access_failed' $false $false
        return 'blocked'
    }
}

function Get-SafeMetadata([string]$Path, [string]$Stage) {
    $ancestors = [Collections.Generic.Stack[string]]::new()
    $parent = [IO.Path]::GetDirectoryName($Path)
    while (-not [string]::IsNullOrEmpty($parent)) {
        $ancestors.Push($parent)
        $parent = [IO.Path]::GetDirectoryName($parent)
    }
    while ($ancestors.Count -gt 0) {
        $kind = Get-Metadata $ancestors.Pop() $Stage
        if ($kind -eq 'blocked' -or $kind -eq 'missing') { return $kind }
        if ($kind -ne 'directory') {
            Emit $Stage 'member_kind_invalid' $false $true
            return 'blocked'
        }
    }
    return Get-Metadata $Path $Stage
}

function Get-Children([string]$Path, [string]$Stage) {
    # Recheck ancestors immediately before each nonrecursive enumeration.
    if ((Get-SafeMetadata $Path $Stage) -ne 'directory') { return }
    try { [IO.Directory]::GetFileSystemEntries($Path) } catch {
        Emit $Stage 'metadata_access_failed' $false $false
    }
}

function Check-Required([string]$Path, [string]$Kind, [string]$Stage, [string]$MissingCode) {
    $actual = Get-SafeMetadata $Path $Stage
    if ($actual -eq 'blocked') { return }
    if ($actual -eq 'missing') { Emit $Stage $MissingCode $false $true; return }
    if ($actual -ne $Kind) { Emit $Stage 'member_kind_invalid' $false $true; return }
}

function Get-LocalAbsolute([string]$Value) {
    # Local drive-qualified paths only, excluding UNC/device/relative/ADS paths.
    if ($Value -notmatch '^[A-Za-z]:[\\/]' -or $Value.Substring(2).Contains(':')) { return $null }
    return [IO.Path]::GetFullPath($Value)
}

try {
    $release = Get-LocalAbsolute $ReleaseDirectory
    $local = Get-LocalAbsolute $env:LOCALAPPDATA
    if ([string]::IsNullOrEmpty($release) -or [string]::IsNullOrEmpty($local)) {
        Emit 'input' 'input_invalid' $false $true
    } else {
        # Static RC6 inventory from the validated build, not user/bundle JSON.
        $releaseFiles = @(
            'Echo.exe', 'scripts/windows_runtime_manifest.json', 'scripts/qq_napcat_runtime_pins.json',
            'runtime/qq-napcat-candidate/NapCatWinBootHook.dll',
            'runtime/qq-napcat-candidate/NapCatWinBootMain.exe',
            'runtime/qq-napcat-candidate/config/plugins.json',
            'runtime/qq-napcat-candidate/conout-wiJ7YKRd.js',
            'runtime/qq-napcat-candidate/launcher-user.bat',
            'runtime/qq-napcat-candidate/napcat.mjs',
            'runtime/qq-napcat-candidate/native/dpapi/win32-x64/@primno+dpapi.node',
            'runtime/qq-napcat-candidate/native/napi2native/ffmpeg.dll',
            'runtime/qq-napcat-candidate/native/napi2native/napi2native.win32.x64.node',
            'runtime/qq-napcat-candidate/native/packet/MoeHoo.win32.x64.node',
            'runtime/qq-napcat-candidate/native/pty/win32.x64/conpty.node',
            'runtime/qq-napcat-candidate/native/pty/win32.x64/conpty_console_list.node',
            'runtime/qq-napcat-candidate/native/pty/win32.x64/pty.node',
            'runtime/qq-napcat-candidate/native/pty/win32.x64/winpty-agent.exe',
            'runtime/qq-napcat-candidate/native/pty/win32.x64/winpty.dll',
            'runtime/qq-napcat-candidate/node_modules/express/package.json',
            'runtime/qq-napcat-candidate/node_modules/ws/package.json',
            'runtime/qq-napcat-candidate/package.json',
            'runtime/qq-napcat-candidate/qqnt.json',
            'runtime/qq-napcat-candidate/worker/conoutSocketWorker.mjs'
        )
        $pinnedFiles = @(
            'plugins/napcat-plugin-echo/index.mjs',
            'plugins/napcat-plugin-echo/package.json',
            'plugins/napcat-plugin-echo/bridge.mjs',
            'plugins/napcat-plugin-echo/snapshot/snapshot.mjs',
            'plugins/napcat-plugin-echo/snapshot/main_wal.mjs',
            'plugins/napcat-plugin-echo/snapshot/workspace.mjs'
        )
        foreach ($name in $pinnedFiles) { $releaseFiles += 'runtime/qq-napcat-candidate/' + $name }
        foreach ($name in $releaseFiles) {
            Check-Required ([IO.Path]::Combine($release, $name)) 'file' 'release' 'release_resource_missing'
        }
        foreach ($name in @('native', 'node_modules', 'worker', 'static')) {
            $path = [IO.Path]::Combine($release, 'runtime/qq-napcat-candidate/' + $name)
            Check-Required $path 'directory' 'release' 'release_resource_missing'
            if ((Get-SafeMetadata $path 'release') -eq 'directory') {
                $children = @(Get-Children $path 'release')
                if ($children.Count -eq 0) { Emit 'release' 'release_directory_empty' $false $true }
            }
        }
        Emit 'release' 'release_hashes_unverified' $true $false

        $root = [IO.Path]::Combine($local, 'LocalChatAnalyzer/runtime/qq')
        $work = [IO.Path]::Combine($root, $Component)
        $workKind = Get-SafeMetadata $work 'workspace'
        if ($workKind -eq 'missing') { Emit 'workspace' 'workspace_missing' $false $true }
        elseif ($workKind -ne 'blocked' -and $workKind -ne 'directory') { Emit 'workspace' 'member_kind_invalid' $false $true }

        $ownerKind = Get-SafeMetadata ([IO.Path]::Combine($root, $Component + '.owner.json')) 'ownership'
        if ($ownerKind -eq 'missing') { Emit 'ownership' 'owner_missing' $false $true }
        elseif ($ownerKind -eq 'file') { Emit 'ownership' 'ownership_content_unverified' $true $false }
        elseif ($ownerKind -ne 'blocked') { Emit 'ownership' 'member_kind_invalid' $false $true }

        $stageKind = Get-SafeMetadata ([IO.Path]::Combine($root, '.' + $Component + '.staging')) 'staging'
        $stageOwnerKind = Get-SafeMetadata ([IO.Path]::Combine($root, '.' + $Component + '.staging.owner.json')) 'staging'
        if ($stageKind -eq 'file' -or $stageOwnerKind -eq 'directory') { Emit 'staging' 'member_kind_invalid' $false $true }
        $hasStage = $stageKind -eq 'directory' -or $stageKind -eq 'file'
        $hasStageOwner = $stageOwnerKind -eq 'file' -or $stageOwnerKind -eq 'directory'
        if ($hasStage -or $hasStageOwner) {
            if ($workKind -eq 'directory' -and $ownerKind -eq 'file') { Emit 'staging' 'staging_conflict' $false $true }
            elseif ($workKind -eq 'directory' -and $ownerKind -eq 'missing' -and $stageKind -eq 'missing' -and $stageOwnerKind -eq 'file') {
                Emit 'staging' 'publication_incomplete_unverified' $false $false
            } else { Emit 'staging' 'staging_present_unverified' $false $false }
        }
        $leaseKind = Get-SafeMetadata ([IO.Path]::Combine($root, '.' + $Component + '.prepare.lock')) 'lease'
        if ($leaseKind -eq 'missing') { Emit 'lease' 'lease_missing' $false $true }
        elseif ($leaseKind -ne 'blocked' -and $leaseKind -ne 'file') { Emit 'lease' 'member_kind_invalid' $false $true }
        Emit 'lease' 'lease_content_and_lock_unverified' $true $false
        Emit 'workspace' 'hardlinks_and_identity_unverified' $true $false
        Emit 'workspace' 'concurrent_replacement_unverified' $true $false

        if ($workKind -eq 'directory') {
            $expected = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            $directories = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            foreach ($name in $pinnedFiles) {
                [void]$expected.Add($name)
                $parent = $name
                while ($parent.Contains('/')) {
                    $parent = $parent.Substring(0, $parent.LastIndexOf('/'))
                    [void]$directories.Add($parent)
                }
            }
            $found = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            $pending = [Collections.Generic.Queue[string]]::new()
            $pending.Enqueue('')
            $visited = 0
            while ($pending.Count -gt 0) {
                $relative = $pending.Dequeue()
                $directory = [IO.Path]::Combine($work, $relative)
                foreach ($child in @(Get-Children $directory 'workspace')) {
                    $visited++
                    if ($visited -gt 10000) { Emit 'workspace' 'inspection_limit_unverified' $false $false; $pending.Clear(); break }
                    $name = $child.Substring($work.Length + 1).Replace('\', '/')
                    $kind = Get-SafeMetadata $child 'workspace'
                    if ($kind -eq 'blocked') { continue }
                    if ($kind -eq 'missing') { Emit 'workspace' 'metadata_changed' $false $false; continue }
                    $first = $name.Split('/')[0]
                    $mutable = $first -ceq 'config' -or $first -ceq 'cache' -or $first -ceq 'logs'
                    if ($kind -eq 'directory' -and ($mutable -or $directories.Contains($name))) { $pending.Enqueue($name); continue }
                    if ($kind -eq 'file' -and $mutable) {
                        if ($name.Contains('/')) { continue }
                        Emit 'workspace' 'member_kind_invalid' $false $true; continue
                    }
                    if ($kind -eq 'file' -and ($name -ceq 'loadNapCat.js' -or $name -ceq 'qqnt.echo.json')) { continue }
                    if ($kind -eq 'file' -and $expected.Contains($name)) { [void]$found.Add($name); continue }
                    # Classify only after the unchanged allow/refusal rules.
                    # Unknown directories are reported here and never enqueued.
                    $location = 'other'
                    if (-not $name.Contains('/')) { $location = 'workspace_root' }
                    elseif ($name.StartsWith('plugins/napcat-plugin-echo/', [StringComparison]::Ordinal)) { $location = 'echo_plugin' }
                    elseif ($first -ceq 'plugins' -and $name.Split('/').Count -eq 2) { $location = 'plugin_container' }
                    $memberKind = 'other'
                    if ($kind -eq 'file' -or $kind -eq 'directory') { $memberKind = $kind }
                    Emit 'workspace' 'member_unknown' $false $true $location $memberKind
                }
            }
            foreach ($name in $pinnedFiles) {
                if (-not $found.Contains($name)) {
                    # A refused link/access failure is not proof of a missing asset.
                    $kind = Get-SafeMetadata ([IO.Path]::Combine($work, $name)) 'workspace'
                    if ($kind -eq 'missing') { Emit 'workspace' 'pinned_asset_missing' $false $true }
                }
            }
        }
    }
} catch {
    Emit 'diagnostic' 'metadata_access_failed' $false $false
}

if ($script:Failed) {
    Emit 'summary' 'metadata_check_failed' $false $false
    exit 1
}
Emit 'summary' 'metadata_shape_valid_content_unverified' $true $false
exit 0
