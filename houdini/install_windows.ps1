param(
    [string[]]$HoudiniUserDir = @()
)

$ErrorActionPreference = "Stop"
$Version = "0.5.0"
$ReleaseRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PayloadRoot = Join-Path $ReleaseRoot "B2H_Model_Import"

if (-not (Test-Path -LiteralPath $PayloadRoot -PathType Container)) {
    throw "Installation payload is missing: $PayloadRoot"
}

function Get-DocumentRoots {
    $roots = @(
        [Environment]::GetFolderPath("MyDocuments"),
        (Join-Path $env:USERPROFILE "Documents"),
        $(if ($env:OneDrive) { Join-Path $env:OneDrive "Documents" }),
        $(if ($env:OneDriveCommercial) { Join-Path $env:OneDriveCommercial "Documents" })
    )
    return @($roots | Where-Object { $_ } | ForEach-Object {
        try { [System.IO.Path]::GetFullPath($_) } catch { $null }
    } | Where-Object { $_ } | Select-Object -Unique)
}

function Get-InstalledHoudiniVersions {
    $programRoots = @(
        $(if ($env:ProgramFiles) { Join-Path $env:ProgramFiles "Side Effects Software" }),
        $(if (${env:ProgramW6432}) { Join-Path ${env:ProgramW6432} "Side Effects Software" }),
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} "Side Effects Software" })
    ) | Where-Object { $_ } | Select-Object -Unique

    $versions = foreach ($root in $programRoots) {
        if (Test-Path -LiteralPath $root -PathType Container) {
            foreach ($directory in (Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
                if ($directory.Name -match '^Houdini\s+(\d+\.\d+)(?:\.\d+)?$') {
                    $Matches[1]
                }
            }
        }
    }
    return @($versions | Sort-Object -Unique)
}

function Find-HoudiniUserDirectories {
    $documentRoots = @(Get-DocumentRoots)
    $targets = @()

    foreach ($root in $documentRoots) {
        if (Test-Path -LiteralPath $root -PathType Container) {
            $targets += Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^houdini\d+(\.\d+)?$' } |
                ForEach-Object { $_.FullName }
        }
    }

    $preferredRoot = $documentRoots | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
    if (-not $preferredRoot) {
        $preferredRoot = Join-Path $env:USERPROFILE "Documents"
    }

    foreach ($houdiniVersion in (Get-InstalledHoudiniVersions)) {
        $folderName = "houdini$houdiniVersion"
        $alreadyFound = $targets | Where-Object {
            [System.IO.Path]::GetFileName($_) -ieq $folderName
        } | Select-Object -First 1
        if (-not $alreadyFound) {
            $targets += Join-Path $preferredRoot $folderName
        }
    }

    return @($targets | Where-Object { $_ } | ForEach-Object {
        [System.IO.Path]::GetFullPath($_)
    } | Sort-Object -Unique)
}

$InstallRoot = Join-Path $env:LOCALAPPDATA "B2H\ModelImport\$Version"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Path (Join-Path $PayloadRoot "*") -Destination $InstallRoot -Recurse -Force

$normalizedRoot = $InstallRoot.Replace([char]92, [char]47)
$package = [ordered]@{
    enable = $true
    env = @(
        [ordered]@{ B2H_ASSET_LIBRARY_ROOT = $normalizedRoot },
        [ordered]@{ PYTHONPATH = "$normalizedRoot/python" }
    )
    path = $normalizedRoot
}
$packageJson = $package | ConvertTo-Json -Depth 6
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$targets = if ($HoudiniUserDir.Count -gt 0) {
    @($HoudiniUserDir | Where-Object { $_ } | ForEach-Object { [System.IO.Path]::GetFullPath($_) } | Sort-Object -Unique)
} else {
    @(Find-HoudiniUserDirectories)
}

if ($targets.Count -eq 0) {
    throw "No Houdini versions were found. Run Houdini once, or pass -HoudiniUserDir with one or more folders."
}

$results = @()
foreach ($target in $targets) {
    $PackageDir = Join-Path $target "packages"
    $PanelDir = Join-Path $target "python_panels"
    $PackagePath = Join-Path $PackageDir "B2H_Model_Import.json"
    $LegacyPackagePath = Join-Path $PackageDir "B2H_Asset_Library.json"
    $PanelPath = Join-Path $PanelDir "b2h_asset_library.pypanel"
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $BackupDir = Join-Path $target "b2h_backup\$Timestamp"

    New-Item -ItemType Directory -Force -Path $target, $PackageDir, $PanelDir | Out-Null

    $existing = @($PackagePath, $LegacyPackagePath, $PanelPath) | Where-Object { Test-Path -LiteralPath $_ }
    if ($existing.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        foreach ($path in $existing) {
            Copy-Item -LiteralPath $path -Destination (Join-Path $BackupDir ([System.IO.Path]::GetFileName($path))) -Force
        }
    }

    Copy-Item -LiteralPath (Join-Path $PayloadRoot "b2h_asset_library.pypanel") -Destination $PanelPath -Force
    [System.IO.File]::WriteAllText($PackagePath, $packageJson, $utf8NoBom)

    if ((Test-Path -LiteralPath $LegacyPackagePath) -and ($LegacyPackagePath -ne $PackagePath)) {
        Move-Item -LiteralPath $LegacyPackagePath -Destination ($LegacyPackagePath + ".disabled.$Timestamp") -Force
    }

    $results += [pscustomobject]@{
        HoudiniUserDir = $target
        PackagePath = $PackagePath
        PanelPath = $PanelPath
        BackupDir = $(if ($existing.Count -gt 0) { $BackupDir } else { "" })
    }
}

Write-Host ""
Write-Host "B2H Model Import $Version installed successfully." -ForegroundColor Green
Write-Host "Application files: $InstallRoot"
Write-Host "Houdini versions configured: $($results.Count)"
foreach ($result in $results) {
    Write-Host ""
    Write-Host "  Houdini user folder: $($result.HoudiniUserDir)"
    Write-Host "  Package file:        $($result.PackagePath)"
    Write-Host "  Python Panel:        $($result.PanelPath)"
    if ($result.BackupDir) {
        Write-Host "  Backup:              $($result.BackupDir)"
    }
}
Write-Host ""
Write-Host "Restart every running Houdini version, then open B2H Model Import v0.5.0."
