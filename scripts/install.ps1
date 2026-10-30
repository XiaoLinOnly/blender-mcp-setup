#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipAddon,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Find-Uvx {
    $command = Get-Command uvx -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidate = Join-Path $HOME ".local\bin\uvx.exe"
    if (Test-Path $candidate) {
        return $candidate
    }
    throw "uvx not found. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}

$uvx = Find-Uvx
Write-Host "uvx: $uvx"

if (-not $SkipAddon) {
    $addonArgs = @("mcp-for-blender", "install-addon")
    if ($DryRun) {
        Write-Host ("Dry run: & `"$uvx`" " + ($addonArgs -join " "))
    }
    else {
        & $uvx @addonArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Blender addon install failed with exit code $LASTEXITCODE"
        }
    }
}

$entry = [ordered]@{
    blender = [ordered]@{
        command = $uvx
        args    = @("mcp-for-blender")
    }
}

Write-Host ""
Write-Host 'Add this under "mcpServers" in %USERPROFILE%\.qoder-cn\settings.json:'
$entry | ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Open Blender (GUI) -> Edit > Preferences > Add-ons -> enable 'Interface: MCP for Blender' -> Save Preferences."
Write-Host "  2. Open the 3D Viewport sidebar (N) -> tab 'MCP for Blender' -> it should say 'Connected on port 9876'."
Write-Host "  3. Restart Qoder or open a new chat session, then verify with: python scripts/probe_blender_mcp.py"
