# Brice PC launch helper (Infopathy and any future PC projects).
#
# Runs in Mark's interactive user session (started at logon by the scheduled task that
# install-warp-watcher.ps1 registers). It watches a trigger folder that the OpenClaw
# container writes to and, for an allowlisted project, opens a VISIBLE Warp window running
# `claude` in that project's directory. Because remoteControlAtStartup is on, that session
# is remote-controllable from the Claude app right away.
#
# Security model:
# - Only project NAMES present in $Projects are honored. The trigger file's CONTENT is
#   ignored entirely - the helper never runs anything from it.
# - The only command ever launched is `claude`, in a fixed directory. This is not a shell.
# - Unknown or malformed triggers are logged and deleted.

$ErrorActionPreference = 'Stop'

# --- allowlist: PC projects only (project name -> working directory) ---
$Projects = @{
  'infopathy' = 'C:\Users\markr\workspace\infopathy-workspace'
}

$RepoData     = Join-Path (Split-Path $PSScriptRoot -Parent) 'data'
$TriggerDir   = Join-Path $RepoData 'launch-triggers'
$WarpExe      = Join-Path $env:LOCALAPPDATA 'Programs\Warp\warp.exe'
# Warp reads launch configs from Roaming AppData on Windows (NOT Local).
$LaunchCfgDir = Join-Path $env:APPDATA 'warp\Warp\data\launch_configurations'
$StateDir     = Join-Path $env:LOCALAPPDATA 'brice-launch'
$LogFile      = Join-Path $StateDir 'watcher.log'
$RateSeconds  = 60          # at most one launch per project per minute
$PollSeconds  = 2

New-Item -ItemType Directory -Force -Path $TriggerDir, $StateDir, $LaunchCfgDir | Out-Null

function Write-Log([string]$m) {
  $ts = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
  Add-Content -Path $LogFile -Value "$ts $m"
}

Write-Log "watcher started; watching $TriggerDir"

while ($true) {
  Start-Sleep -Seconds $PollSeconds
  $files = @(Get-ChildItem -Path $TriggerDir -File -ErrorAction SilentlyContinue)
  foreach ($f in $files) {
    $name = $f.BaseName.ToLower().Trim()
    try {
      if (-not $Projects.ContainsKey($name)) { Write-Log "ignored unknown project '$name'"; continue }
      $dir = $Projects[$name]
      if (-not (Test-Path $dir)) { Write-Log "missing directory for '$name': $dir"; continue }

      $stamp = Join-Path $StateDir "last-$name"
      if (Test-Path $stamp) {
        $age = ((Get-Date) - (Get-Item $stamp).LastWriteTime).TotalSeconds
        if ($age -lt $RateSeconds) { Write-Log "rate-limited '$name' ($([int]$age)s < ${RateSeconds}s)"; continue }
      }

      $cfgName = "brice-$name.yaml"
      $cfgPath = Join-Path $LaunchCfgDir $cfgName
      $cwd = ($dir -replace '\\', '/')
      $yaml = @"
---
name: brice-$name
windows:
  - tabs:
      - layout:
          cwd: "$cwd"
          commands:
            - exec: claude
"@
      # Write UTF-8 with no BOM (Warp's YAML parser dislikes a BOM).
      [System.IO.File]::WriteAllText($cfgPath, $yaml)
      Start-Process "warp://launch/$cfgName"
      Set-Content -Path $stamp -Value (Get-Date).ToString('o')
      Write-Log "launched '$name' in $dir"
    } catch {
      Write-Log "error handling '$name': $($_.Exception.Message)"
    } finally {
      Remove-Item -Path $f.FullName -Force -ErrorAction SilentlyContinue
    }
  }
}
