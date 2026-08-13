# Give .molom savefiles the MoloM icon in Explorer, and open them on double-click.
#
#   powershell -ExecutionPolicy Bypass -File tools\associate_molom_files.ps1
#   powershell -ExecutionPolicy Bypass -File tools\associate_molom_files.ps1 -Remove
#
# WHY THIS IS A SEPARATE SCRIPT, and not something MoloM does at startup:
# a file association is a change to YOUR system, not to the program, and a
# program that quietly claims a file extension the first time it runs is a
# program people learn to distrust. So it is opt-in, it is reversible with
# -Remove, and you run it yourself.
#
# Everything here is written under HKEY_CURRENT_USER, so it needs no
# administrator rights and affects only your account. It touches exactly three
# keys, all under HKCU:\Software\Classes:
#   .molom                     -> points at the MoloM.Project type
#   MoloM.Project\DefaultIcon  -> the icon Explorer draws
#   MoloM.Project\shell\open   -> what a double-click runs
#
# NOTE: the window icon inside MoloM is a different thing entirely and already
# works - this is only about how Explorer draws the FILES.

[CmdletBinding()]
param(
    [switch]$Remove,
    [string]$IconPath,
    [string]$Launcher
)

$ErrorActionPreference = 'Stop'
$progId   = 'MoloM.Project'
$classes  = 'HKCU:\Software\Classes'
$extKey   = Join-Path $classes '.molom'
$progKey  = Join-Path $classes $progId

function Refresh-Shell {
    # Explorer caches icons aggressively; without this the change only shows up
    # after a re-login, which reads as "it did not work".
    $sig = @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, uint flags, System.IntPtr item1, System.IntPtr item2);
'@
    try {
        $t = Add-Type -MemberDefinition $sig -Name 'MoloMShell' -Namespace 'W' -PassThru
        $t::SHChangeNotify(0x08000000, 0x1000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)
    } catch {
        Write-Warning "Could not refresh the icon cache; log out and back in to see the change."
    }
}

if ($Remove) {
    foreach ($key in @($extKey, $progKey)) {
        if (Test-Path $key) {
            Remove-Item $key -Recurse -Force
            Write-Host "removed $key"
        }
    }
    Refresh-Shell
    Write-Host "`n.molom is no longer associated with MoloM."
    return
}

# --- the icon ---------------------------------------------------------------
if (-not $IconPath) {
    $IconPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'molom\resources\molom.ico'
}
$IconPath = (Resolve-Path -LiteralPath $IconPath).Path
if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "Icon not found: $IconPath"
}

# --- what a double-click should run -----------------------------------------
# The installed console script is preferred: it is a real .exe, so Explorer
# shows it sensibly and it does not depend on which python is first on PATH.
if (-not $Launcher) {
    $cmd = Get-Command molom -ErrorAction SilentlyContinue
    if ($cmd) {
        $Launcher = '"{0}" "%1"' -f $cmd.Source
    } else {
        $py = (Get-Command pythonw -ErrorAction SilentlyContinue)
        if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
        if (-not $py) { throw "Found neither 'molom' nor python on PATH; pass -Launcher yourself." }
        $Launcher = '"{0}" -m molom "%1"' -f $py.Source
    }
}

New-Item -Path $extKey -Force | Out-Null
Set-ItemProperty -Path $extKey -Name '(default)' -Value $progId

New-Item -Path $progKey -Force | Out-Null
Set-ItemProperty -Path $progKey -Name '(default)' -Value 'MoloM project'

$iconKey = Join-Path $progKey 'DefaultIcon'
New-Item -Path $iconKey -Force | Out-Null
Set-ItemProperty -Path $iconKey -Name '(default)' -Value ('"{0}",0' -f $IconPath)

$openKey = Join-Path $progKey 'shell\open\command'
New-Item -Path $openKey -Force | Out-Null
Set-ItemProperty -Path $openKey -Name '(default)' -Value $Launcher

Refresh-Shell

Write-Host "`n.molom files now use the MoloM icon."
Write-Host "  icon    : $IconPath"
Write-Host "  opens   : $Launcher"
Write-Host "`nUndo with:  powershell -ExecutionPolicy Bypass -File tools\associate_molom_files.ps1 -Remove"
Write-Host "If the desktop still shows the old icon, press F5 there Explorer caches them."
