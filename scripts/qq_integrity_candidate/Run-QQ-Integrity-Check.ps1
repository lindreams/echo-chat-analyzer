$ErrorActionPreference = 'Stop'

# This launcher ships beside Echo/, outside the validated portable tree.
# Each invocation has its own Echo settings/runtime workspace and result file.
# Keep the normal QQ profile locations so the authorized local QQ login can
# access its existing history; this script never opens a chat database.
$EchoExecutable = Join-Path $PSScriptRoot 'Echo\Echo.exe'
if (-not (Test-Path -LiteralPath $EchoExecutable -PathType Leaf)) {
    Write-Host 'Incomplete candidate. Extract the entire ZIP first.'
    exit 1
}
$EchoCheckRun = Join-Path $PSScriptRoot ('check-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $EchoCheckRun | Out-Null
$EchoCheckOutput = Join-Path $EchoCheckRun 'integrity-result.json'
$env:LOCALAPPDATA = Join-Path $EchoCheckRun 'local-app-data'
New-Item -ItemType Directory -Path $env:LOCALAPPDATA | Out-Null
$env:ECHO_QQ_INTEGRITY_CHECK = '1'
$env:ECHO_QQ_INTEGRITY_CHECK_OUTPUT = $EchoCheckOutput
Write-Host 'QQ integrity candidate 1 (based on 0.2.2). Close other Echo instances first.'
Write-Host 'Connect QQ once, wait for the result in Echo, then close Echo normally.'
try {
    $EchoCheckProcess = Start-Process -FilePath $EchoExecutable -WorkingDirectory $EchoCheckRun -WindowStyle Normal -PassThru
    $EchoCheckProcess.WaitForExit()
} catch {
    # Never print raw process exceptions (which can include private paths).
    Write-Host 'Candidate could not start. No integrity result was collected.'
    exit 1
}
if (-not (Test-Path -LiteralPath $EchoCheckOutput -PathType Leaf)) {
    # No SQLite result is inferred when acquisition/login did not reach it.
    $EchoCheckFallback = '{"probe":"qq-integrity-1","initial_check":"not_reached","cleanup":"not_observed"}'
    $EchoCheckStream = [IO.File]::Open($EchoCheckOutput, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $EchoCheckBytes = [Text.Encoding]::UTF8.GetBytes($EchoCheckFallback + "`n")
        $EchoCheckStream.Write($EchoCheckBytes, 0, $EchoCheckBytes.Length)
    } finally { $EchoCheckStream.Dispose() }
}
Write-Host 'Send ONLY integrity-result.json from this folder:'
Write-Host $EchoCheckRun
Write-Host 'Do not send the local-app-data folder, logs, screenshots or database files.'
