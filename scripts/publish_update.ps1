param(
    [string]$Version = "",
    [string]$Notes = "",
    [switch]$PromptUpdate,
    [string]$BaseUrl = "https://greenjiao.github.io/Game-Map-Tracker/update/",
    [string]$CommitMessage = "",
    [switch]$SkipBuild,
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$ErrorMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage，退出码：$LASTEXITCODE"
    }
}

function Invoke-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 @args
    } else {
        & python @args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python 命令执行失败，退出码：$LASTEXITCODE"
    }
}

function Read-RequiredText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt
    )

    while ($true) {
        $value = (Read-Host $Prompt).Trim()
        if ($value) {
            return $value
        }
        Write-Host "此项不能为空，请重新输入。"
    }
}

function Read-YesNo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,
        [Parameter(Mandatory = $true)]
        [bool]$DefaultYes
    )

    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $value = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
        if (-not $value) {
            return $DefaultYes
        }
        if ($value -in @("y", "yes")) {
            return $true
        }
        if ($value -in @("n", "no")) {
            return $false
        }
        Write-Host "请输入 y 或 n。"
    }
}

if (-not $Version.Trim()) {
    $Version = Read-RequiredText "请输入发布版本号，例如 0.1.1"
} else {
    $Version = $Version.Trim()
}

if (-not $Notes.Trim()) {
    $Notes = Read-RequiredText "请输入更新说明"
} else {
    $Notes = $Notes.Trim()
}

$UsePromptUpdate = $false
if ($PSBoundParameters.ContainsKey("PromptUpdate")) {
    $UsePromptUpdate = [bool]$PromptUpdate
} else {
    $UsePromptUpdate = Read-YesNo "是否启动后弹窗提示更新？" $false
}

$ShouldBuild = $true
if ($PSBoundParameters.ContainsKey("SkipBuild")) {
    $ShouldBuild = -not [bool]$SkipBuild
} else {
    $ShouldBuild = Read-YesNo "是否重新打包？" $true
}

$ShouldCommitAndPush = $true
if ($PSBoundParameters.ContainsKey("SkipPush")) {
    $ShouldCommitAndPush = -not [bool]$SkipPush
} else {
    $ShouldCommitAndPush = Read-YesNo "是否提交并推送？" $true
}

if (-not $CommitMessage.Trim()) {
    $defaultCommitMessage = "Publish GMT-N $Version update"
    if ($ShouldCommitAndPush) {
        $inputCommitMessage = (Read-Host "请输入提交信息，直接回车使用默认值：$defaultCommitMessage").Trim()
        $CommitMessage = if ($inputCommitMessage) { $inputCommitMessage } else { $defaultCommitMessage }
    } else {
        $CommitMessage = $defaultCommitMessage
    }
} else {
    $CommitMessage = $CommitMessage.Trim()
}

Write-Host ""
Write-Host "发布参数："
Write-Host "  版本号：$Version"
Write-Host "  更新说明：$Notes"
Write-Host "  启动弹窗：$UsePromptUpdate"
Write-Host "  重新打包：$ShouldBuild"
Write-Host "  提交推送：$ShouldCommitAndPush"
Write-Host "  更新源：$BaseUrl"
Write-Host ""

if ($ShouldBuild) {
    Write-Host "开始打包..."
    Invoke-CheckedCommand `
        -Command { & powershell -ExecutionPolicy Bypass -File "scripts/build_windows.ps1" -Clean } `
        -ErrorMessage "打包失败"
} elseif (-not (Test-Path "dist\GMT-N")) {
    throw "已选择跳过打包，但 dist\GMT-N 不存在。"
}

$UpdateDir = Join-Path $Root "docs\update"
$DistDir = Join-Path $Root "dist\GMT-N"
$ManifestPath = Join-Path $UpdateDir "app-manifest.json"

if (-not (Test-Path $DistDir)) {
    throw "发布目录不存在：$DistDir"
}

Write-Host "重建 docs/update..."
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $UpdateDir
New-Item -ItemType Directory -Force $UpdateDir | Out-Null
Copy-Item (Join-Path $DistDir "*") $UpdateDir -Recurse -Force

Write-Host "生成更新清单..."
$manifestArgs = @(
    "scripts/generate_update_manifest.py",
    "dist/GMT-N",
    "--version", $Version,
    "--base-url", $BaseUrl,
    "--notes", $Notes,
    "-o", $ManifestPath
)
if ($UsePromptUpdate) {
    $manifestArgs += "--prompt-update"
}
Invoke-Python @manifestArgs

Write-Host "暂存 docs/update..."
Invoke-CheckedCommand -Command { & git add docs/update } -ErrorMessage "git add 失败"

Write-Host ""
Write-Host "当前暂存变更："
& git status --short
Write-Host ""
& git diff --cached --stat

& git diff --cached --quiet -- docs/update
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "docs/update 没有新的暂存变更，本次不提交。"
    exit 0
}

if (-not $ShouldCommitAndPush) {
    Write-Host ""
    Write-Host "已完成生成和暂存，按你的选择不提交推送。"
    exit 0
}

$confirmed = Read-YesNo "确认提交并推送以上暂存变更？" $true
if (-not $confirmed) {
    Write-Host "已取消提交推送，变更仍保留在暂存区。"
    exit 0
}

Write-Host "提交更新包..."
Invoke-CheckedCommand -Command { & git commit -m $CommitMessage -- docs/update } -ErrorMessage "git commit 失败"

Write-Host "推送到 GitHub..."
Invoke-CheckedCommand -Command { & git push } -ErrorMessage "git push 失败"

Write-Host ""
Write-Host "更新发布完成。"
Write-Host "Manifest 地址：$($BaseUrl.TrimEnd('/'))/app-manifest.json"
