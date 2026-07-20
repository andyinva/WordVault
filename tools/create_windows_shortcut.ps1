# ---------------------------------------------------------------------------
# create_windows_shortcut.ps1 - put a WordVault icon on the Windows desktop.
#
# Run it once from the repository folder:
#
#     cd "C:\Users\Andrew Hopkins\Documents\WordVault"
#     powershell -ExecutionPolicy Bypass -File tools\create_windows_shortcut.ps1
#
# What it does:
#   * finds pythonw.exe (the console-less Python, so no black window opens)
#   * creates "WordVault.lnk" on the desktop that runs:  pythonw -m wordvault
#   * sets the working directory to this repository (required, because the
#     wordvault package is imported from here rather than installed)
#   * uses assets\wordvault.ico as the icon when present
#
# The editor opens the default library (~\.wordvault\library.db), the same
# one the command line uses. Delete the shortcut any time; this script only
# creates that one .lnk file and changes nothing else.
#
# NOTE for contributors: keep this file pure ASCII. Windows PowerShell 5
# reads .ps1 files without a BOM as ANSI, so characters like em dashes
# get mangled and break parsing.
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

# Repository root = the parent of the tools\ folder this script lives in.
$repo = Split-Path -Parent $PSScriptRoot

# Prefer pythonw.exe (no console window); fall back to python.exe if needed.
$pythonw = Get-Command pythonw -ErrorAction SilentlyContinue
if ($pythonw) {
    $target = $pythonw.Source
} else {
    Write-Host "pythonw.exe not found on PATH; using python.exe (a console window will show)."
    $target = (Get-Command python).Source
}

$desktop  = [Environment]::GetFolderPath("Desktop")
$linkPath = Join-Path $desktop "WordVault.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($linkPath)
$lnk.TargetPath       = $target
$lnk.Arguments        = "-m wordvault"
$lnk.WorkingDirectory = $repo
$lnk.Description      = "WordVault - version-tracking writing environment"

# Custom icon, if the assets folder has one.
$icon = Join-Path $repo "assets\wordvault.ico"
if (Test-Path $icon) {
    $lnk.IconLocation = "$icon,0"
}

$lnk.Save()
Write-Host "Created: $linkPath"
Write-Host "Target:  $target -m wordvault  (starting in $repo)"
