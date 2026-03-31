param(
    [int]$DPI = 300,
    [int]$ColorIntent = 2,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$scanner = $null
$deviceManager = $null

try {
    $deviceManager = New-Object -ComObject WIA.DeviceManager
    $scanner = $null

    foreach ($info in $deviceManager.DeviceInfos) {
        if ($info.Type -eq 1) {
            $scanner = $info.Connect()
            break
        }
    }

    if ($scanner -eq $null) {
        Write-Output "ERROR:No scanner found. Check USB cable and HP drivers."
        exit 1
    }

    $item = $scanner.Items.Item(1)

    # Set scan properties (DPI and color mode)
    try {
        foreach ($prop in $item.Properties) {
            switch ($prop.PropertyID) {
                6147 { $prop.Value = $DPI }   # Horizontal Resolution
                6148 { $prop.Value = $DPI }   # Vertical Resolution
                6146 { $prop.Value = $ColorIntent }  # Current Intent
            }
        }
    } catch {
        # Some scanners don't support all properties — continue with defaults
    }

    # Delete leftover temp file if it exists
    if (Test-Path $OutputPath) { Remove-Item $OutputPath -Force }

    # Transfer image as BMP
    $formatBMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
    $image = $item.Transfer($formatBMP)
    $image.SaveFile($OutputPath)

    Write-Output "OK"

} catch {
    Write-Output "ERROR:$($_.Exception.Message)"
    exit 1
} finally {
    # Properly release COM objects so the scanner doesn't stay locked
    if ($item) {
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($item) | Out-Null } catch {}
    }
    if ($scanner) {
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($scanner) | Out-Null } catch {}
    }
    if ($deviceManager) {
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($deviceManager) | Out-Null } catch {}
    }
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
