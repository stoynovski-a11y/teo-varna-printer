# Provision NAPS2 (portable variant — no installer, no admin install).
# Idempotent: exits 0 immediately if NAPS2 is already available.
# Called by СТАРТИРАЙ СКЕНЕР.bat on first launch.
$ErrorActionPreference = 'Stop'

$portableDir = Join-Path $env:LOCALAPPDATA 'HPScanner\naps2-portable'

# Where we'd find NAPS2.Console.exe in any provisioning mode
$candidates = @(
    'C:\Program Files\NAPS2\NAPS2.Console.exe',
    'C:\Program Files (x86)\NAPS2\NAPS2.Console.exe',
    (Join-Path $portableDir 'NAPS2.Console.exe'),
    (Join-Path $portableDir 'App\NAPS2.Console.exe')
)
foreach ($p in $candidates) {
    if (Test-Path $p) {
        Write-Host "[OK] NAPS2 already available at $p"
        exit 0
    }
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Hardcoded direct URL — avoids the GitHub API entirely. Pin to a known
# good release; bump the version manually when newer is needed.
$url = 'https://github.com/cyanfish/naps2/releases/download/v8.2.1/naps2-8.2.1-win-x64.zip'
$zip = Join-Path $env:TEMP 'naps2-portable.zip'

try {
    Write-Host '[..] Downloading NAPS2 portable from GitHub...'
    Invoke-WebRequest $url -OutFile $zip -UseBasicParsing -TimeoutSec 90
    $size = (Get-Item $zip).Length
    Write-Host "[OK] Downloaded $([math]::Round($size / 1MB, 1)) MB"
} catch {
    Write-Host "[!] Download failed: $_"
    Write-Host "    Falling back to WIA scan path."
    exit 1
}

try {
    if (Test-Path $portableDir) { Remove-Item $portableDir -Recurse -Force }
    New-Item -ItemType Directory -Path $portableDir -Force | Out-Null

    Write-Host '[..] Extracting...'
    Expand-Archive -Path $zip -DestinationPath $portableDir -Force
    Remove-Item $zip -ErrorAction SilentlyContinue

    foreach ($p in $candidates) {
        if (Test-Path $p) {
            Write-Host "[OK] NAPS2 ready at $p"
            exit 0
        }
    }

    # Some portable builds nest everything under a top-level folder. Search.
    $exe = Get-ChildItem -Path $portableDir -Filter 'NAPS2.Console.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) {
        Write-Host "[OK] NAPS2 ready at $($exe.FullName)"
        exit 0
    }

    Write-Host "[!] Extracted but NAPS2.Console.exe not found in $portableDir"
    exit 1

} catch {
    Write-Host "[!] Extract failed: $_"
    exit 1
}
