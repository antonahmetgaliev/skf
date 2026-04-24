#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Renames a Windows local user account from "Pidor" to "Vlad",
    including profile folder, registry entries, and Shell Folders.

.DESCRIPTION
    Run this script as Administrator. It will:
      1. Create a System Restore Point
      2. Rename the local account (SAM name + display name)
      3. Update the profile path in the registry (ProfileList)
      4. Update HKCU Shell Folders that reference the old path
      5. Schedule a one-shot SYSTEM startup task to rename C:\Users\Pidor -> C:\Users\Vlad
    After running the script, REBOOT. The folder rename happens automatically on boot.

.NOTES
    - Must be run as Administrator
    - Tested on Windows 10/11
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$OldName  = 'Pidor'
$NewName  = 'Vlad'
$OldProfilePath = "C:\Users\$OldName"
$NewProfilePath = "C:\Users\$NewName"
$TaskName = '_RenameUserProfile_OneShot'

# ─── 0. Safety check ────────────────────────────────────────────────────────
if (-not (Get-LocalUser -Name $OldName -ErrorAction SilentlyContinue)) {
    Write-Error "Local user '$OldName' not found. Aborting."
    exit 1
}

if (Get-LocalUser -Name $NewName -ErrorAction SilentlyContinue) {
    Write-Error "A local user named '$NewName' already exists. Aborting."
    exit 1
}

Write-Host "`n=== Renaming Windows user: $OldName -> $NewName ===" -ForegroundColor Cyan

# ─── 1. System Restore Point ────────────────────────────────────────────────
Write-Host "`n[1/5] Creating System Restore Point..." -ForegroundColor Yellow
try {
    Enable-ComputerRestore -Drive "C:\" -ErrorAction SilentlyContinue
    Checkpoint-Computer -Description "Before renaming user $OldName to $NewName" -RestorePointType MODIFY_SETTINGS
    Write-Host "     Restore point created." -ForegroundColor Green
} catch {
    Write-Warning "Could not create restore point (non-fatal): $_"
}

# ─── 2. Rename local account ────────────────────────────────────────────────
Write-Host "`n[2/5] Renaming local account..." -ForegroundColor Yellow
Rename-LocalUser -Name $OldName -NewName $NewName
Set-LocalUser   -Name $NewName -FullName $NewName -Description ''
Write-Host "     Account renamed to '$NewName'." -ForegroundColor Green

# ─── 3. Update ProfileList in registry (ProfileImagePath) ───────────────────
Write-Host "`n[3/5] Updating ProfileList registry (ProfileImagePath)..." -ForegroundColor Yellow

$profileListKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
$sid = $null

Get-ChildItem $profileListKey | ForEach-Object {
    $path = (Get-ItemProperty $_.PSPath -Name ProfileImagePath -ErrorAction SilentlyContinue).ProfileImagePath
    if ($path -and $path -ieq $OldProfilePath) {
        $sid = $_.PSChildName
        Set-ItemProperty $_.PSPath -Name ProfileImagePath -Value $NewProfilePath
        Write-Host "     Updated SID $sid : $OldProfilePath -> $NewProfilePath" -ForegroundColor Green
    }
}

if (-not $sid) {
    Write-Warning "No ProfileList entry found for '$OldProfilePath'. Profile path may already be different."
}

# ─── 4. Update HKCU Shell Folders (safe to do while logged in) ──────────────
Write-Host "`n[4/5] Updating HKCU Shell Folders..." -ForegroundColor Yellow

$shellKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
)

foreach ($keyPath in $shellKeys) {
    if (-not (Test-Path $keyPath)) { continue }
    $key = Get-Item $keyPath
    foreach ($valueName in $key.GetValueNames()) {
        $val = $key.GetValue($valueName, '', 'DoNotExpandEnvironmentNames')
        if ($val -is [string] -and $val -imatch [regex]::Escape($OldName)) {
            $newVal = $val -ireplace [regex]::Escape($OldName), $NewName
            Set-ItemProperty $keyPath -Name $valueName -Value $newVal
            Write-Host "     [$valueName] $val -> $newVal" -ForegroundColor Green
        }
    }
}

# Also update the same keys under the user's SID in HKLM (rare, but possible)
if ($sid) {
    $hklmUserKey = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid"
    # Already handled above
}

# ─── 5. Schedule profile folder rename on next boot (as SYSTEM) ─────────────
Write-Host "`n[5/5] Scheduling profile folder rename on next boot..." -ForegroundColor Yellow

# Remove any leftover task with same name
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$renameScript = @"
`$src = '$OldProfilePath'
`$dst = '$NewProfilePath'
if (Test-Path `$src) {
    if (-not (Test-Path `$dst)) {
        Rename-Item -Path `$src -NewName '$NewName' -Force
    }
}
# Self-destruct
Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false -ErrorAction SilentlyContinue
"@

$encodedScript = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($renameScript))

$action  = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -EncodedCommand $encodedScript"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -RunLevel Highest `
    -LogonType ServiceAccount

Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "     Scheduled task '$TaskName' created (runs as SYSTEM on next boot)." -ForegroundColor Green

# ─── Done ────────────────────────────────────────────────────────────────────
Write-Host @"

============================================================
  DONE. Summary:
    Account name : $OldName  ->  $NewName
    Profile path : $OldProfilePath  ->  $NewProfilePath (on reboot)
    Registry     : ProfileList + Shell Folders updated

  NEXT STEP: REBOOT the computer.
    On the next startup the folder C:\Users\$OldName will be
    automatically renamed to C:\Users\$NewName before you log in.

  If you see any apps referencing the old path after reboot,
  log out and back in — most paths are resolved at login time.
============================================================
"@ -ForegroundColor Cyan
