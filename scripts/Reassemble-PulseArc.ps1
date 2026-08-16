$ErrorActionPreference = 'Stop'

$baseName = 'PulseArc-0.1.0-beta.1-Installer.img'
$parts = Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter "$baseName.part-*" |
    Sort-Object Name

if ($parts.Count -eq 0) {
    throw "No $baseName.part-* files were found beside this script."
}

$outputPath = Join-Path $PSScriptRoot $baseName
$output = [System.IO.File]::Create($outputPath)
try {
    foreach ($part in $parts) {
        Write-Host "Joining $($part.Name)..."
        $input = [System.IO.File]::OpenRead($part.FullName)
        try {
            $input.CopyTo($output)
        }
        finally {
            $input.Dispose()
        }
    }
}
finally {
    $output.Dispose()
}

$expected = (Get-Content -LiteralPath (Join-Path $PSScriptRoot "$baseName.sha256") -Raw).Split()[0]
$actual = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected.ToLowerInvariant()) {
    throw "SHA-256 verification failed. Delete the rebuilt image and download every part again."
}

Write-Host "Verified: $outputPath"
