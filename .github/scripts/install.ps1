param(
  [string]$Repo = $(if ($env:MONO_COPILOT_REPO) { $env:MONO_COPILOT_REPO } else { "mosesgameli/mono-copilot" }),
  [string]$Tag = $(if ($env:MONO_COPILOT_TAG) { $env:MONO_COPILOT_TAG } else { "latest" })
)

$ErrorActionPreference = "Stop"

function Show-Usage {
  Write-Host "Usage: install.ps1 -Repo owner/repo [-Tag vX.Y.Z|latest]"
  Write-Host "Env alternatives:"
  Write-Host "  MONO_COPILOT_REPO=owner/repo"
  Write-Host "  MONO_COPILOT_TAG=vX.Y.Z|latest"
}

if ([string]::IsNullOrWhiteSpace($Repo)) {
  Write-Host "Error: Repo is required."
  Show-Usage
  exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
  Write-Host "Python is required."
  exit 1
}

$apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
if ($Tag -ne "latest") {
  $apiUrl = "https://api.github.com/repos/$Repo/releases/tags/$Tag"
}

$tmpDir = Join-Path $env:TEMP ("mono-copilot-install-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $tmpDir | Out-Null

try {
  $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "mono-copilot-installer" }

  $copilotAsset = $release.assets | Where-Object { $_.name -match "^copilot-.*\.whl$" } | Select-Object -First 1
  if (-not $copilotAsset) {
    Write-Host "No copilot wheel found in release assets."
    exit 1
  }

  $runtimeAsset = $release.assets | Where-Object { $_.name -match "^runtime-.*\.whl$" } | Select-Object -First 1

  $copilotWheel = Join-Path $tmpDir $copilotAsset.name
  Invoke-WebRequest -Uri $copilotAsset.browser_download_url -OutFile $copilotWheel

  if ($runtimeAsset) {
    $runtimeWheel = Join-Path $tmpDir $runtimeAsset.name
    Invoke-WebRequest -Uri $runtimeAsset.browser_download_url -OutFile $runtimeWheel
  }

  $pipx = Get-Command pipx -ErrorAction SilentlyContinue
  if ($pipx) {
    Write-Host "Installing with pipx..."
    & pipx install --force --pip-args "--find-links $tmpDir" $copilotWheel
  } else {
    Write-Host "pipx not found, falling back to python user install..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
      & py -m pip install --user --upgrade pip
      & py -m pip install --user --upgrade --find-links $tmpDir $copilotWheel
    } else {
      & python -m pip install --user --upgrade pip
      & python -m pip install --user --upgrade --find-links $tmpDir $copilotWheel
    }
  }

  $mono = Get-Command mono-copilot -ErrorAction SilentlyContinue
  if ($mono) {
    & mono-copilot --help | Out-Null
    Write-Host "Installed successfully. Run: mono-copilot"
    exit 0
  }

  Write-Host "Install completed, but mono-copilot is not on PATH in this shell."
  Write-Host "If pipx was used, run: pipx ensurepath"
  Write-Host "If pip --user was used, ensure your Python Scripts directory is on PATH."
  exit 1
}
finally {
  Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}