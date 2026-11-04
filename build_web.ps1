$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$OutputDir = Join-Path $ProjectRoot "App_web"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"

Write-Host "Building AIDM Web..."

foreach ($dir in @($OutputDir, $DistDir, $BuildDir)) {
    if (Test-Path $dir) {
        Remove-Item -Recurse -Force $dir
    }
}

python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name "AIDM" `
    --icon (Join-Path $ProjectRoot "AIDM_ICO.ico") `
    --add-data "$(Join-Path $ProjectRoot 'AIDM_ICO.ico');." `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $BuildDir `
    --paths $ProjectRoot `
    --add-data "$(Join-Path $ProjectRoot 'web\static');web/static" `
    --collect-submodules uvicorn `
    --hidden-import web.server `
    --hidden-import web.session `
    --hidden-import web.netbind `
    --hidden-import web.launch_dialog `
    --exclude-module matplotlib `
    --exclude-module numpy `
    --exclude-module PyQt5 `
    --exclude-module PIL `
    --exclude-module pygame `
    --exclude-module IPython `
    --exclude-module pytest `
    (Join-Path $ProjectRoot "run_web.py")

New-Item -ItemType Directory -Path $OutputDir | Out-Null
Copy-Item (Join-Path $DistDir "AIDM.exe") $OutputDir

$WorldsDest = Join-Path $OutputDir "worlds"
New-Item -ItemType Directory -Path $WorldsDest | Out-Null
$WorkflowsDest = Join-Path $OutputDir "workflows"
New-Item -ItemType Directory -Path $WorkflowsDest | Out-Null

# Пустой шаблон, без ключей и чужих миров: эту папку можно класть в zip.
@'
{
  "api_url": "http://localhost:1234/v1/chat/completions",
  "api_key": "",
  "model": "",
  "active_api_preset": "",
  "api_presets": [],
  "temperature": 0.7,
  "max_tokens": 300,
  "context_size": 16384,
  "summary_fill_percent": 80,
  "memory_interval": 5,
  "memory_top_k": 5,
  "stream_mode": true,
  "summary_enabled": true,
  "memory_enabled": true,
  "image_prompt_style": "sd",
  "image_backend": "off",
  "comfy_url": "http://127.0.0.1:8188",
  "a1111_url": "http://127.0.0.1:7860",
  "comfy_workflow": "scene_api.json",
  "image_width": 1024,
  "image_height": 1024,
  "image_steps": 28,
  "image_auto": false,
  "image_send_negative": true,
  "language": "ru",
  "lan_access": true,
  "bind_mode": "lan"
}
'@ | Set-Content -Path (Join-Path $WorldsDest "settings.json") -Encoding UTF8

Write-Host "Done: $OutputDir\AIDM.exe"
Write-Host "Zip the App_web folder. Worlds stay next to AIDM.exe."
