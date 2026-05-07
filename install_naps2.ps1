# Silent NAPS2 install. Idempotent — exits 0 immediately if already installed.
# Called by СТАРТИРАЙ СКЕНЕР.bat on first launch. Runs as admin (caller is admin).
$ErrorActionPreference = 'Stop'

$paths = @(
    'C:\Program Files\NAPS2\NAPS2.Console.exe',
    'C:\Program Files (x86)\NAPS2\NAPS2.Console.exe'
)
foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Host "[OK] NAPS2 already installed at $p"
        exit 0
    }
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

try {
    Write-Host '[..] Querying GitHub for latest NAPS2 release...'
    $rel = Invoke-RestMethod 'https://api.github.com/repos/cyanfish/naps2/releases/latest'

    # NAPS2 ships e.g. naps2-8.2.1-win-x64.exe (Inno Setup installer)
    $asset = $rel.assets | Where-Object { $_.name -like 'naps2-*-win-x64.exe' } | Select-Object -First 1
    if (-not $asset) {
        throw "No win-x64.exe asset found in latest release"
    }

    $setup = Join-Path $env:TEMP 'naps2-setup.exe'
    Write-Host "[..] Downloading $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)..."
    Invoke-WebRequest $asset.browser_download_url -OutFile $setup -UseBasicParsing

    Write-Host '[..] Installing silently (Inno Setup VERYSILENT)...'
    $proc = Start-Process $setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "setup.exe exited with code $($proc.ExitCode)"
    }

    Remove-Item $setup -ErrorAction SilentlyContinue

    foreach ($p in $paths) {
        if (Test-Path $p) {
            Write-Host "[OK] NAPS2 installed at $p"
            exit 0
        }
    }
    throw "Install reported success but NAPS2.Console.exe not found in expected locations"

} catch {
    Write-Host "[!] NAPS2 install failed: $_"
    Write-Host "    The app will fall back to the WIA scan path."
    exit 1
}
