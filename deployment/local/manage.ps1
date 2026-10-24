param(
    [ValidateSet('Install', 'Start', 'Stop', 'Status', 'Configure', 'Build')]
    [string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$script:Local = $PSScriptRoot
$script:Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$script:EnvFile = Join-Path $script:Local '.env'
$script:ManifestFile = Join-Path $script:Local 'release.json'
$script:Settings = @{}

function Invoke-Docker([string[]]$Arguments) {
    # 捕获输出，失败只显示步骤名；不回显容器配置或可能含凭据的驱动异常。
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $script:Docker @Arguments 2>$null
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($code -ne 0) { throw "Docker 步骤未完成：$($Arguments[0])。请确认引擎状态、磁盘空间和安装说明。" }
    return ($output -join "`n")
}

function Confirm-Docker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $command) {
        $candidates = @(
            (Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin/docker.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe')
        )
        $candidate = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $candidate) { throw '请先安装 Docker Desktop，再运行本入口。' }
        $script:Docker = $candidate
    } else { $script:Docker = $command.Source }
    $platform = Invoke-Docker @('info', '--format', '{{.OSType}}/{{.Architecture}}')
    if ($platform -notmatch '^linux/(x86_64|amd64)$') { throw '本安装包适用于 x64 Windows 的 Docker Desktop Linux 容器模式。' }
    $null = Invoke-Docker @('compose', 'version')
}

function New-Hex([int]$Length) {
    $bytes = New-Object byte[] $Length
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

function Get-Sha256([string]$Path) {
    # 使用系统自带 .NET，不依赖 Windows PowerShell 的 Get-FileHash 函数自动加载。
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Find-Port([int]$Preferred, [int[]]$Excluded) {
    foreach ($candidate in @($Preferred, 0, 0)) {
        $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $candidate)
        try {
            $listener.Start()
            $chosen = $listener.LocalEndpoint.Port
            if ($chosen -notin $Excluded) { return $chosen }
        } catch { } finally { $listener.Stop() }
    }
    throw '没有找到可用的本机端口。'
}

function Write-Settings {
    $lines = @('# 本机私有配置。请保留；不要上传 GitHub，不要更换已有数据库密码。')
    foreach ($key in ($script:Settings.Keys | Sort-Object)) {
        $value = [string]$script:Settings[$key]
        if ($value -match "['`r`n]") { throw '配置值包含不支持的字符。' }
        $lines += "$key='$value'"
    }
    $temporary = $script:EnvFile + '.tmp'
    [IO.File]::WriteAllLines($temporary, $lines, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $script:EnvFile -Force
}

function Read-Settings([bool]$AllowCreate = $false) {
    if (-not (Test-Path -LiteralPath $script:EnvFile)) {
        if (-not $AllowCreate) { throw '请先运行“安装并启动.cmd”；尚未生成本机配置。' }
        $appPort = Find-Port 17401 @()
        $s3Port = Find-Port 17413 @($appPort)
        $consolePort = Find-Port 17414 @($appPort, $s3Port)
        $script:Settings = @{
            INSTALL_ID = (New-Hex 8); LOCAL_PG_PASSWORD = (New-Hex 24)
            LOCAL_S3_PASSWORD = (New-Hex 24); LOCAL_JWT_SECRET = (New-Hex 48)
            LOCAL_APP_PORT = "$appPort"; LOCAL_S3_PORT = "$s3Port"; LOCAL_CONSOLE_PORT = "$consolePort"
            DASHSCOPE_API_KEY = ''; PLANNER_MODEL = 'qwen3.6-flash'; IMAGE_PROVIDER = 'mock'
            BACKGROUND_PROVIDER = 'disabled'; OUTPAINTING_PROVIDER = 'disabled'
            UPSCALING_PROVIDER = 'disabled'; REGION_PROVIDER = 'disabled'; REFERENCE_GENERATION_ENABLED = 'false'
        }
        Write-Settings
        Write-Host '已生成独立配置与随机密码，不复用开发环境的账号或数据。'
    }
    $script:Settings = @{}
    foreach ($line in [IO.File]::ReadAllLines($script:EnvFile, [Text.Encoding]::UTF8)) {
        if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $value = $Matches[2].Trim()
            if ($value.StartsWith("'") -and $value.EndsWith("'")) { $value = $value.Substring(1, $value.Length - 2) }
            $script:Settings[$Matches[1]] = $value
        }
    }
    if ($script:Settings.INSTALL_ID -notmatch '^[a-f0-9]{16}$') { throw '安装编号无效；请保留原配置核对，不能覆盖已有数据归属。' }
    foreach ($key in @('LOCAL_PG_PASSWORD', 'LOCAL_S3_PASSWORD', 'LOCAL_JWT_SECRET')) {
        if ($script:Settings[$key] -notmatch '^[a-f0-9]{48,96}$') { throw '本机服务凭据格式无效，请保留原配置核对。' }
    }
    $ports = @()
    foreach ($key in @('LOCAL_APP_PORT', 'LOCAL_S3_PORT', 'LOCAL_CONSOLE_PORT')) {
        $value = 0
        if (-not [int]::TryParse($script:Settings[$key], [ref]$value) -or $value -lt 1024 -or $value -gt 65535 -or $value -in $ports) {
            throw '本机端口必须在 1024～65535 之间且互不相同。'
        }
        $ports += $value
    }
    # Compose 的系统环境变量优先于 env 文件；仅在本启动进程中移除同名变量，保证使用本包配置。
    foreach ($key in $script:Settings.Keys) { [Environment]::SetEnvironmentVariable($key, $null, 'Process') }
    $script:ComposeArgs = @('compose', '--project-name', ('aie-local-' + $script:Settings.INSTALL_ID),
        '--project-directory', $script:Local, '--env-file', $script:EnvFile, '-f', (Join-Path $script:Local 'compose.yml'))
    $null = Invoke-Docker ($script:ComposeArgs + @('config', '--quiet'))
}

function Read-Manifest {
    if (-not (Test-Path -LiteralPath $script:ManifestFile)) { throw '尚无镜像清单。源码版请先运行“从源码构建.cmd”。' }
    $script:Manifest = Get-Content -LiteralPath $script:ManifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($script:Manifest.version -ne 'local-20261025' -or $script:Manifest.platform -ne 'linux/amd64') { throw '安装包清单版本不匹配。' }
}

function Confirm-Files([bool]$AllFiles = $false) {
    foreach ($entry in $script:Manifest.files) {
        if (-not $AllFiles -and $entry.path -notlike 'deployment/local/models/*') { continue }
        $target = [IO.Path]::GetFullPath((Join-Path $script:Root $entry.path))
        if (-not $target.StartsWith($script:Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '清单路径超出安装目录。' }
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "安装文件缺失：$($entry.path)" }
        if ((Get-Sha256 $target) -ne $entry.sha256) { throw "安装文件校验失败：$($entry.path)。原文件保留，请重新解压。" }
    }
}

function Confirm-Images {
    foreach ($entry in $script:Manifest.images) {
        $actual = Invoke-Docker @('image', 'inspect', $entry.tag, '--format', '{{.Id}}')
        if ($actual.Trim() -ne $entry.id) { throw "镜像与安装清单不一致：$($entry.tag)。请重新运行安装入口导入。" }
    }
}

function Confirm-Idle {
    $running = Invoke-Docker ($script:ComposeArgs + @('ps', '--status', 'running', '--services'))
    if (($running -split "`n") -contains 'postgres') {
        $count = Invoke-Docker ($script:ComposeArgs + @('exec', '-T', 'postgres', 'psql', '-U', 'picturelocal', '-d', 'ai_picture_local', '-tAc',
            "SELECT (SELECT count(*) FROM tool_runs WHERE status IN ('queued','running')) + (SELECT count(*) FROM agent_turns WHERE status IN ('planning','running'))"))
        if ([int]$count.Trim() -gt 0) { throw '还有排队或运行中的修图任务，请完成后再停止或更换配置。' }
    }
}

function Start-Local {
    Confirm-Images
    Confirm-Files
    Confirm-Idle
    Write-Host '正在启动独立本机服务并检查数据库、存储与任务进程……'
    $null = Invoke-Docker ($script:ComposeArgs + @('up', '-d', '--wait', '--wait-timeout', '180', '--pull', 'never', '--no-build'))
    $url = 'http://127.0.0.1:' + $script:Settings.LOCAL_APP_PORT
    $health = Invoke-RestMethod -Uri ($url + '/api/health') -TimeoutSec 10
    if ($health.database -ne 'ok') { throw '页面服务已启动，但数据库检查未通过。' }
    Write-Host ("启动完成，请在浏览器打开：" + $url + '/editor')
    Write-Host '首次使用请在网页注册自己的账号。没有预设登录账号。'
    if (-not $script:Settings.DASHSCOPE_API_KEY) { Write-Host '尚未配置百炼密钥：本地编辑可用，AI规划不可用，文生图仅为占位图。' }
}

function Build-Source {
    if (-not (Test-Path -LiteralPath (Join-Path $script:Root 'Dockerfile'))) { throw '此入口需要完整源码；离线安装包请直接安装。' }
    Write-Host '正在从源码构建应用与本地服务镜像，首次需要联网，可能耗时较长……'
    $source = Join-Path $script:Root 'third_party/minio/minio-source.tar.gz'
    if ((Get-Sha256 $source) -ne 'be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c') { throw 'MinIO 源码校验失败。' }
    $cache = Join-Path $script:Root 'infrastructure/minio/.cache'
    $null = New-Item -ItemType Directory -Path $cache -Force
    Copy-Item -LiteralPath $source -Destination (Join-Path $cache 'minio-source.tar.gz') -Force
    $null = Invoke-Docker @('build', '-t', 'ai-picture-editor-app:local-20261025', $script:Root)
    $null = Invoke-Docker @('build', '-t', 'ai-picture-editor-minio:local-20261025', (Join-Path $script:Root 'infrastructure/minio'))
    foreach ($pair in @(@('postgres:17-alpine', 'ai-picture-editor-postgres:local-20261025'), @('redis:7-alpine', 'ai-picture-editor-redis:local-20261025'))) {
        $null = Invoke-Docker @('pull', '--platform', 'linux/amd64', $pair[0])
        $null = Invoke-Docker @('tag', $pair[0], $pair[1])
    }
    $models = Get-Content -LiteralPath (Join-Path $script:Local 'models.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $files = @()
    foreach ($entry in $models) {
        $path = Join-Path $script:Root $entry.path
        if (-not (Test-Path -LiteralPath $path)) {
            $null = New-Item -ItemType Directory -Path (Split-Path $path) -Force
            $temporary = $path + '.download'
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri $entry.url -OutFile $temporary -UseBasicParsing -TimeoutSec 600
                if ((Get-Sha256 $temporary) -ne $entry.sha256) { throw '模型下载校验失败，保留下载文件供核对。' }
                Move-Item -LiteralPath $temporary -Destination $path
            } catch { throw '本地模型未准备完成；请按 models.json 中的公开来源与校验值补齐后重试。' }
        }
        if ((Get-Sha256 $path) -ne $entry.sha256) { throw '已有模型校验失败，未覆盖原文件。' }
        $files += @{path = $entry.path; sha256 = $entry.sha256}
    }
    $images = @()
    foreach ($tag in @('ai-picture-editor-app:local-20261025', 'ai-picture-editor-postgres:local-20261025', 'ai-picture-editor-redis:local-20261025', 'ai-picture-editor-minio:local-20261025')) {
        $images += @{tag = $tag; id = (Invoke-Docker @('image', 'inspect', $tag, '--format', '{{.Id}}')).Trim()}
    }
    $record = @{version = 'local-20261025'; platform = 'linux/amd64'; images = $images; files = $files}
    [IO.File]::WriteAllText($script:ManifestFile, ($record | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    Write-Host '源码构建与模型准备完成。下一步运行“安装并启动.cmd”。'
}

try {
    Confirm-Docker
    if ($Action -eq 'Build') { Build-Source; exit 0 }
    Read-Manifest
    if ($Action -eq 'Install') {
        Write-Host '正在校验安装文件，首次导入镜像需要几分钟……'
        Confirm-Files $true
        $archive = Join-Path $script:Local 'images/images.tar'
        if (Test-Path -LiteralPath $archive) { $null = Invoke-Docker @('image', 'load', '--input', $archive) }
    }
    Read-Settings ($Action -eq 'Install')
    switch ($Action) {
        'Install' { Start-Local }
        'Start' { Start-Local }
        'Stop' {
            Confirm-Idle
            $null = Invoke-Docker ($script:ComposeArgs + @('down', '--timeout', '45'))
            Write-Host '本机服务已停止。数据库、图片、队列数据和登录配置均已保留。'
        }
        'Status' {
            Write-Host (Invoke-Docker ($script:ComposeArgs + @('ps', '--all', '--format', 'table {{.Service}}\t{{.State}}\t{{.Health}}')))
            Write-Host ('访问地址：http://127.0.0.1:' + $script:Settings.LOCAL_APP_PORT + '/editor')
        }
        'Configure' {
            Confirm-Idle
            Write-Host '请输入北京地域百炼 API Key（输入不回显）。留空取消，不修改原配置。'
            $secure = Read-Host -AsSecureString
            $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim() }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secure.Dispose() }
            if (-not $key) { Write-Host '已取消。'; exit 0 }
            if ($key -notmatch '^[A-Za-z0-9_-]{16,256}$') { throw '密钥格式不正确，未保存。' }
            $script:Settings.DASHSCOPE_API_KEY = $key
            foreach ($name in @('IMAGE_PROVIDER', 'BACKGROUND_PROVIDER', 'OUTPAINTING_PROVIDER', 'UPSCALING_PROVIDER', 'REGION_PROVIDER')) { $script:Settings[$name] = 'dashscope' }
            Write-Settings
            $key = $null
            Write-Host '已保存到本包 deployment/local/.env。将启用AI功能；实际操作可能产生平台费用，当前不发起模型调用。'
            Start-Local
        }
    }
} catch {
    # 仅抛出本脚本的固定提示；其他异常可能包含连接配置，不直接输出。
    if ($_.Exception -is [Management.Automation.RuntimeException] -and $_.Exception.Message -notmatch 'Invoke-|https?://|password|secret|sk-') {
        Write-Host ('未完成：' + $_.Exception.Message) -ForegroundColor Red
    } else { Write-Host '未完成：请检查 Docker、安装文件与端口配置。已有数据和配置保留。' -ForegroundColor Red }
    exit 1
}
