<#
.SYNOPSIS
  Regression checks for TEST-001 runner failure/cleanup behavior using fake docker commands.

.DESCRIPTION
  Validates failure-path and cleanup-target behavior without touching real Docker resources.
  This script does not run backend tests; it drives controlled failures before Python execution.

.EXAMPLE
  .\scripts\run-backend-test-infra-regression.ps1
#>
[CmdletBinding()]
param(
    [string]$RunnerPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RunnerPath)) {
    $scriptDir = if ($PSScriptRoot) {
        $PSScriptRoot
    }
    else {
        Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $RunnerPath = Join-Path $scriptDir "run-backend-test-infra.ps1"
}

if (-not (Test-Path -LiteralPath $RunnerPath -PathType Leaf)) {
    throw "Runner script was not found at $RunnerPath"
}

$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Message)
    $failures.Add($Message)
    Write-Host "FAIL: $Message" -ForegroundColor Red
}

function Add-Pass {
    param([string]$Message)
    Write-Host "PASS: $Message" -ForegroundColor Green
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if ($Condition) {
        Add-Pass $Message
    }
    else {
        Add-Failure $Message
    }
}

function New-Sandbox {
    param(
        [string]$ScenarioName,
        [bool]$CreateComposeFile,
        [bool]$CreatePythonMarker
    )

    $path = Join-Path $env:TEMP ("mvp27_runner_regression_{0}_{1}" -f $ScenarioName, [Guid]::NewGuid().ToString("N"))
    $scriptsDir = Join-Path $path "scripts"
    New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
    Copy-Item -LiteralPath $RunnerPath -Destination (Join-Path $scriptsDir "run-backend-test-infra.ps1")

    if ($CreateComposeFile) {
        @"
services:
  db:
    image: postgres:16
"@ | Set-Content -LiteralPath (Join-Path $path "docker-compose.yml") -Encoding ASCII
    }

    if ($CreatePythonMarker) {
        $pythonMarkerDir = Join-Path $path ".venv\Scripts"
        New-Item -ItemType Directory -Path $pythonMarkerDir -Force | Out-Null
        # Marker file is enough because these scenarios fail before Python is executed.
        Set-Content -LiteralPath (Join-Path $pythonMarkerDir "python.exe") -Value "placeholder" -Encoding ASCII
    }

    return $path
}

function New-FakeDockerBin {
    param([string]$SandboxPath)

    $fakeBin = Join-Path $SandboxPath "fakebin"
    New-Item -ItemType Directory -Path $fakeBin -Force | Out-Null

    @'
@echo off
setlocal
if "%FAKE_DOCKER_LOG%"=="" exit /b 97

echo %*>>"%FAKE_DOCKER_LOG%"
set "ARGS= %* "

echo %ARGS% | findstr /I /C:" up " >nul
if %errorlevel%==0 exit /b %FAKE_DOCKER_UP_EXIT%

echo %ARGS% | findstr /I /C:" down " >nul
if %errorlevel%==0 exit /b %FAKE_DOCKER_DOWN_EXIT%

echo %ARGS% | findstr /I /C:" exec " >nul
if %errorlevel%==0 exit /b %FAKE_DOCKER_EXEC_EXIT%

exit /b 0
'@ | Set-Content -LiteralPath (Join-Path $fakeBin "docker.cmd") -Encoding ASCII

    return $fakeBin
}

function Get-EnvSnapshot {
    param([string[]]$Names)

    $snapshot = @{}
    foreach ($name in $Names) {
        $item = Get-Item "Env:$name" -ErrorAction SilentlyContinue
        $snapshot[$name] = [PSCustomObject]@{
            Present = ($null -ne $item)
            Value = if ($item) { $item.Value } else { $null }
        }
    }
    return $snapshot
}

function Restore-EnvSnapshot {
    param([hashtable]$Snapshot)

    foreach ($name in $Snapshot.Keys) {
        $state = $Snapshot[$name]
        if ($state.Present) {
            Set-Item "Env:$name" -Value $state.Value
        }
        else {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

function Get-ArgValue {
    param(
        [string]$Line,
        [string]$ArgName
    )

    $pattern = '--{0}\s+(?:"([^"]+)"|(\S+))' -f [Regex]::Escape($ArgName)
    $match = [Regex]::Match($Line, $pattern)
    if ($match.Success) {
        if ($match.Groups[1].Success) {
            return $match.Groups[1].Value
        }
        return $match.Groups[2].Value
    }
    return $null
}

function Read-DockerLog {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        return @(Get-Content -LiteralPath $Path)
    }
    return @()
}

function Invoke-Runner {
    param(
        [string]$ScriptPath,
        [string]$CallerLocation
    )

    $result = [PSCustomObject]@{
        Threw = $false
        Message = $null
        LocationRestored = $false
    }

    $originalLocation = Get-Location
    try {
        Set-Location -LiteralPath $CallerLocation
        try {
            & $ScriptPath -SkipFullSuite
        }
        catch {
            $result.Threw = $true
            $result.Message = $_.Exception.Message
        }
        $result.LocationRestored = ((Get-Location).Path -eq (Get-Item -LiteralPath $CallerLocation).FullName)
    }
    finally {
        Set-Location -LiteralPath $originalLocation
    }

    return $result
}

# Scenario 1: Missing venv with a preexisting compose project must not trigger cleanup docker calls.
$scenario1 = New-Sandbox -ScenarioName "missingvenv" -CreateComposeFile $true -CreatePythonMarker $false
$scenario1Runner = Join-Path $scenario1 "scripts\run-backend-test-infra.ps1"
$scenario1FakeBin = New-FakeDockerBin -SandboxPath $scenario1
$scenario1Log = Join-Path $scenario1 "docker.log"
$scenario1Caller = Join-Path $scenario1 "caller"
New-Item -ItemType Directory -Path $scenario1Caller -Force | Out-Null

$envNames = @(
    "PATH",
    "FAKE_DOCKER_LOG",
    "FAKE_DOCKER_UP_EXIT",
    "FAKE_DOCKER_DOWN_EXIT",
    "FAKE_DOCKER_EXEC_EXIT",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_FILE"
)
$envSnapshot = Get-EnvSnapshot -Names $envNames

try {
    $env:PATH = "$scenario1FakeBin;$env:PATH"
    $env:FAKE_DOCKER_LOG = $scenario1Log
    $env:FAKE_DOCKER_UP_EXIT = "0"
    $env:FAKE_DOCKER_DOWN_EXIT = "0"
    $env:FAKE_DOCKER_EXEC_EXIT = "0"
    $env:COMPOSE_PROJECT_NAME = "caller_project_should_not_be_used"
    $env:COMPOSE_FILE = "caller_compose_should_not_be_used.yml"

    $run = Invoke-Runner -ScriptPath $scenario1Runner -CallerLocation $scenario1Caller
    $dockerCalls = Read-DockerLog -Path $scenario1Log

    Assert-True $run.Threw "Scenario 1: runner fails when venv is missing"
    Assert-True ($run.Message -like "Expected Python interpreter*") "Scenario 1: missing-venv error is surfaced"
    Assert-True ($dockerCalls.Count -eq 0) "Scenario 1: no docker call happens when startup never begins"
    Assert-True $run.LocationRestored "Scenario 1: caller location is restored"
    Assert-True ($env:COMPOSE_PROJECT_NAME -eq "caller_project_should_not_be_used") "Scenario 1: caller COMPOSE_PROJECT_NAME remains unchanged"
}
finally {
    Restore-EnvSnapshot -Snapshot $envSnapshot
}

# Scenario 2: Failure before startup (compose file missing) must not trigger teardown.
$scenario2 = New-Sandbox -ScenarioName "prestartfailure" -CreateComposeFile $false -CreatePythonMarker $true
$scenario2Runner = Join-Path $scenario2 "scripts\run-backend-test-infra.ps1"
$scenario2FakeBin = New-FakeDockerBin -SandboxPath $scenario2
$scenario2Log = Join-Path $scenario2 "docker.log"
$scenario2Caller = Join-Path $scenario2 "caller"
New-Item -ItemType Directory -Path $scenario2Caller -Force | Out-Null
$envSnapshot = Get-EnvSnapshot -Names $envNames

try {
    $env:PATH = "$scenario2FakeBin;$env:PATH"
    $env:FAKE_DOCKER_LOG = $scenario2Log
    $env:FAKE_DOCKER_UP_EXIT = "0"
    $env:FAKE_DOCKER_DOWN_EXIT = "0"
    $env:FAKE_DOCKER_EXEC_EXIT = "0"
    $env:COMPOSE_PROJECT_NAME = "caller_project_should_not_be_used"

    $run = Invoke-Runner -ScriptPath $scenario2Runner -CallerLocation $scenario2Caller
    $dockerCalls = Read-DockerLog -Path $scenario2Log

    Assert-True $run.Threw "Scenario 2: runner fails when compose file is missing"
    Assert-True ($run.Message -like "Expected docker compose file*") "Scenario 2: pre-start failure reason is compose config"
    Assert-True ($dockerCalls.Count -eq 0) "Scenario 2: no teardown docker call when startup was never attempted"
    Assert-True $run.LocationRestored "Scenario 2: caller location is restored"
}
finally {
    Restore-EnvSnapshot -Snapshot $envSnapshot
}

# Scenario 3: compose up partial failure must teardown only generated project and explicit compose file.
$scenario3 = New-Sandbox -ScenarioName "uppartial" -CreateComposeFile $true -CreatePythonMarker $true
$scenario3Runner = Join-Path $scenario3 "scripts\run-backend-test-infra.ps1"
$scenario3FakeBin = New-FakeDockerBin -SandboxPath $scenario3
$scenario3Log = Join-Path $scenario3 "docker.log"
$scenario3Caller = Join-Path $scenario3 "caller"
New-Item -ItemType Directory -Path $scenario3Caller -Force | Out-Null
$envSnapshot = Get-EnvSnapshot -Names $envNames

try {
    $env:PATH = "$scenario3FakeBin;$env:PATH"
    $env:FAKE_DOCKER_LOG = $scenario3Log
    $env:FAKE_DOCKER_UP_EXIT = "42"
    $env:FAKE_DOCKER_DOWN_EXIT = "0"
    $env:FAKE_DOCKER_EXEC_EXIT = "0"
    $env:COMPOSE_PROJECT_NAME = "caller_preexisting_project"

    $run = Invoke-Runner -ScriptPath $scenario3Runner -CallerLocation $scenario3Caller
    $dockerCalls = Read-DockerLog -Path $scenario3Log
    $upLine = $dockerCalls | Where-Object { $_ -match " up " } | Select-Object -First 1
    $downLine = $dockerCalls | Where-Object { $_ -match " down " } | Select-Object -First 1

    $expectedComposeFile = (Join-Path $scenario3 "docker-compose.yml")
    $upProject = if ($upLine) { Get-ArgValue -Line $upLine -ArgName "project-name" } else { $null }
    $downProject = if ($downLine) { Get-ArgValue -Line $downLine -ArgName "project-name" } else { $null }
    $upFile = if ($upLine) { Get-ArgValue -Line $upLine -ArgName "file" } else { $null }
    $downFile = if ($downLine) { Get-ArgValue -Line $downLine -ArgName "file" } else { $null }

    Assert-True $run.Threw "Scenario 3: runner fails when compose up fails"
    Assert-True ($run.Message -like "Step failed: Start isolated DB service*") "Scenario 3: primary error is the compose up failure"
    Assert-True ($null -ne $upLine) "Scenario 3: compose up is called"
    Assert-True ($null -ne $downLine) "Scenario 3: teardown is called after partial startup"
    Assert-True ($upProject -like "mvp27_test001_*") "Scenario 3: generated project name is used for compose up"
    Assert-True ($downProject -eq $upProject) "Scenario 3: teardown uses the same generated project"
    Assert-True ($upFile -eq $expectedComposeFile) "Scenario 3: compose up uses explicit compose file"
    Assert-True ($downFile -eq $expectedComposeFile) "Scenario 3: compose down uses explicit compose file"
    Assert-True (-not ($dockerCalls -join "`n" -match "caller_preexisting_project")) "Scenario 3: inherited project name is not used"
    Assert-True $run.LocationRestored "Scenario 3: caller location is restored"
}
finally {
    Restore-EnvSnapshot -Snapshot $envSnapshot
}

# Scenario 3b: same partial-up failure checks, but sandbox path includes spaces.
$scenario3b = New-Sandbox -ScenarioName "up partial spaced path" -CreateComposeFile $true -CreatePythonMarker $true
$scenario3bRunner = Join-Path $scenario3b "scripts\run-backend-test-infra.ps1"
$scenario3bFakeBin = New-FakeDockerBin -SandboxPath $scenario3b
$scenario3bLog = Join-Path $scenario3b "docker.log"
$scenario3bCaller = Join-Path $scenario3b "caller path with spaces"
New-Item -ItemType Directory -Path $scenario3bCaller -Force | Out-Null
$envSnapshot = Get-EnvSnapshot -Names $envNames

try {
    $env:PATH = "$scenario3bFakeBin;$env:PATH"
    $env:FAKE_DOCKER_LOG = $scenario3bLog
    $env:FAKE_DOCKER_UP_EXIT = "42"
    $env:FAKE_DOCKER_DOWN_EXIT = "0"
    $env:FAKE_DOCKER_EXEC_EXIT = "0"

    $run = Invoke-Runner -ScriptPath $scenario3bRunner -CallerLocation $scenario3bCaller
    $dockerCalls = Read-DockerLog -Path $scenario3bLog
    $upLine = $dockerCalls | Where-Object { $_ -match " up " } | Select-Object -First 1
    $downLine = $dockerCalls | Where-Object { $_ -match " down " } | Select-Object -First 1

    $expectedComposeFile = (Join-Path $scenario3b "docker-compose.yml")
    $upFile = if ($upLine) { Get-ArgValue -Line $upLine -ArgName "file" } else { $null }
    $downFile = if ($downLine) { Get-ArgValue -Line $downLine -ArgName "file" } else { $null }

    Assert-True $run.Threw "Scenario 3b: runner fails when compose up fails"
    Assert-True ($null -ne $upLine) "Scenario 3b: compose up is called"
    Assert-True ($null -ne $downLine) "Scenario 3b: teardown is called after partial startup"
    Assert-True ($upLine -match '--file\s+"') "Scenario 3b: docker log contains quoted --file argument"
    Assert-True ($downLine -match '--file\s+"') "Scenario 3b: teardown log contains quoted --file argument"
    Assert-True ($upFile -eq $expectedComposeFile) "Scenario 3b: quoted compose up file path is parsed correctly"
    Assert-True ($downFile -eq $expectedComposeFile) "Scenario 3b: quoted compose down file path is parsed correctly"
    Assert-True $run.LocationRestored "Scenario 3b: caller location is restored"
}
finally {
    Restore-EnvSnapshot -Snapshot $envSnapshot
}

# Scenario 4: primary failure must stay primary even when cleanup also fails with EAP=Stop.
$scenario4 = New-Sandbox -ScenarioName "primaryvssecondary" -CreateComposeFile $true -CreatePythonMarker $true
$scenario4Runner = Join-Path $scenario4 "scripts\run-backend-test-infra.ps1"
$scenario4FakeBin = New-FakeDockerBin -SandboxPath $scenario4
$scenario4Log = Join-Path $scenario4 "docker.log"
$envSnapshot = Get-EnvSnapshot -Names $envNames

try {
    $env:PATH = "$scenario4FakeBin;$env:PATH"
    $env:FAKE_DOCKER_LOG = $scenario4Log
    $env:FAKE_DOCKER_UP_EXIT = "42"
    $env:FAKE_DOCKER_DOWN_EXIT = "55"
    $env:FAKE_DOCKER_EXEC_EXIT = "0"

    $childScript = @"
`$ErrorActionPreference = 'Stop'
try {
    & '$scenario4Runner' -SkipFullSuite
    Write-Output 'CHILD_EXIT=0'
    exit 0
}
catch {
    Write-Output ('PRIMARY=' + `$_.Exception.Message)
    exit 1
}
"@

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $childOutput = & powershell.exe -NoProfile -Command $childScript 2>&1
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    $childExitCode = $LASTEXITCODE
    $childText = (($childOutput | ForEach-Object { $_.ToString() }) -join "`n")

    Assert-True ($childExitCode -eq 1) "Scenario 4: child process fails when primary and cleanup both fail"
    Assert-True ($childText -match "PRIMARY=Step failed: Start isolated DB service \(exit code 42\)") "Scenario 4: primary failure remains the compose-up failure"
    Assert-True ($childText -match "Cleanup also failed:") "Scenario 4: cleanup failure is still reported"
    Assert-True ($childText -match "Cleanup failed: docker compose down -v exited with code 55") "Scenario 4: cleanup failure details are preserved"
}
finally {
    Restore-EnvSnapshot -Snapshot $envSnapshot
}

Write-Host ""
Write-Host "Regression check summary:" -ForegroundColor Cyan
if ($failures.Count -eq 0) {
    Write-Host "All runner regression checks passed." -ForegroundColor Green
    exit 0
}

$failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
exit 1
