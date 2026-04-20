param(
    [int]$DPI = 300,
    [int]$ColorIntent = 2,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

# Initialize ALL COM handles at top so finally can release every one,
# even if the script fails partway through.
$deviceManager = $null
$scanner       = $null
$items         = $null
$item          = $null
$image         = $null

try {
    $deviceManager = New-Object -ComObject WIA.DeviceManager

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

    # Capture the Items collection so we can release it (was leaking before).
    $items = $scanner.Items
    $item  = $items.Item(1)

    # Set scan properties (DPI and color mode)
    try {
        foreach ($prop in $item.Properties) {
            switch ($prop.PropertyID) {
                6147 { $prop.Value = $DPI }          # X resolution
                6148 { $prop.Value = $DPI }          # Y resolution
                6146 { $prop.Value = $ColorIntent }  # Current intent
            }
        }
    } catch {
        # Some scanners don't expose these — fall back to defaults
    }

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
    # Release in reverse order of acquisition.
    # $image holds an open handle to the WIA device — release FIRST so the
    # device session closes before we drop the parent objects.
    if ($image)         { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($image)         | Out-Null } catch {} }
    if ($item)          { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($item)          | Out-Null } catch {} }
    if ($items)         { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($items)         | Out-Null } catch {} }
    if ($scanner)       { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($scanner)       | Out-Null } catch {} }
    if ($deviceManager) { try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($deviceManager) | Out-Null } catch {} }

    # Two GC passes — second one catches refs freed by the first.
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
    [System.GC]::Collect()
}
