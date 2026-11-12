# P0.3c：真实 ZMAI 成对运行手动验收

以下命令在 PowerShell 中执行。ZMEvalHub 只读取新运行的 ZMAI 日志；目标工程请使用两份独立、干净且同一提交的临时副本。运行可能调用付费模型，由操作者自行启动。不要用已有 `execution_log.json` 回填采集目录。

## 1. 在每次运行前制作元数据

先切换到 ZMEvalHub 仓库根目录，再执行下列代码。第一次将 `$arm` 设为 `baseline`；第二次改为 `candidate`，其余用例定义、目标提交和执行条件应相同。输入实际模型、Prompt、并发、超时及受控 seed；ZMAI 若没有实际受控 seed，直接回车，记录为 `null`，Gate 会 BLOCKED。不要填写虚构的 seed。

```powershell
$zmai = Read-Host 'ZMAI 仓库绝对路径'
$root = Join-Path (Get-Location).Path '.zmevalhub\acceptance\p03c_real'
$arm = 'baseline'
$target = Read-Host '本次使用的临时目标工程绝对路径'
$task = Read-Host '两次运行完全相同的任务文本'
$configFile = Read-Host '本次 ZMAI 实际配置文件绝对路径'
$modelId = Read-Host '本次实际模型 ID'
$promptVersion = Read-Host '本次 Prompt 版本'
$seedText = Read-Host '实际受控 seed；未提供时直接回车'
$seedValue = if ($seedText.Trim()) { [int]$seedText } else { $null }
$concurrency = [int](Read-Host '实际并发数')
$timeoutMs = [int](Read-Host '实际超时毫秒数')
New-Item -ItemType Directory -Path $root -Force | Out-Null
$targetSha = (git -C $target rev-parse HEAD).Trim()
if (git -C $target status --porcelain) { throw '目标工程不干净；请使用新的临时副本' }
$environmentFile = Join-Path $root "$arm-tool-environment.txt"
$packages = uv pip freeze --python "$zmai\.venv\Scripts\python.exe"
@("os=$([Environment]::OSVersion.VersionString)", "target_sha=$targetSha", $packages) |
  Set-Content -LiteralPath $environmentFile -Encoding utf8
$runId = "$arm-$(Get-Date -Format yyyyMMddHHmmss)"
$spec = @{
  source_run_id = $runId
  source_id = $runId
  dataset_name = 'p03c-real-pair'
  case = @{
    case_id = 'real-case-1'
    kind = 'coding_agent'
    input = @{ task = $task; target_git_sha = $targetSha }
    expected = @{ requires_post_edit_test = $true }
  }
  subject = @{
    name = 'ZMAI'
    git_sha = (git -C $zmai rev-parse HEAD).Trim()
    model_id = $modelId
    config_sha256 = (Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  conditions = @{
    seed = $seedValue
    repetitions = 1
    concurrency = $concurrency
    timeout_ms = $timeoutMs
    tool_environment_sha256 = (Get-FileHash -LiteralPath $environmentFile -Algorithm SHA256).Hash.ToLowerInvariant()
    evaluator_config_sha256 = (Get-FileHash -LiteralPath '.\src\zmevalhub\rules\agent_reliability.py' -Algorithm SHA256).Hash.ToLowerInvariant()
    prompt_version = $promptVersion
  }
}
$specJson = $spec | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText("$root\$arm-spec.json", $specJson, [Text.UTF8Encoding]::new($false))
```

环境清单和配置文件应反映实际运行条件。若两个环境清单因无关文件路径不同而产生不同哈希，请检查内容并重新制作同一语义的环境清单；不要手改哈希。候选运行若有模型、Prompt、代码或配置差异，对比时须逐项声明。

## 2. 先启动观察器，再启动 ZMAI

终端 A（保持运行，等待显示 `capture ready`）：

```powershell
$root = Join-Path (Get-Location).Path '.zmevalhub\acceptance\p03c_real'
$arm = 'baseline'
uv run zmeval watch-zmai "$root\$arm-spec.json" "$root\$arm-capture" --log "$root\$arm-workspace\*\.state\execution_log.json" --timeout-seconds 7200
```

看到 `capture ready` 后，在终端 B 启动本次真实 ZMAI 任务。`$target` 必须是第 1 步使用的临时目标副本。下例使用本机已有 ZMAI 可执行文件，且把工作区放在本次验收目录，不修改 ZMAI 源码：

```powershell
$zmai = Read-Host 'ZMAI 仓库绝对路径'
$root = Join-Path (Get-Location).Path '.zmevalhub\acceptance\p03c_real'
$arm = 'baseline'
$target = Read-Host '第 1 步的临时目标工程绝对路径'
$task = Read-Host '第 1 步使用的同一任务文本'
Set-Location $target
$env:ZMAI_WORKSPACE__ROOT = "$root\$arm-workspace"
& "$zmai\.venv\Scripts\zmai.exe" --max-steps 30 $task
```

终端 A 应输出 `SEALED`。为候选运行准备另一份同一提交的干净临时目标副本，重复第 1、2 步，并把两个终端的 `$arm` 均改为 `candidate`。若日志早于观察器存在、步骤被改写、缺终止事件或超时，观察器返回 BLOCKED，不得把历史日志重新封存为可信运行。

## 3. 离线比较和 Gate

在 ZMEvalHub 仓库根目录执行；仅在实际模型版本不同的情况下保留 `--allow-difference model_id`，其他差异按实际情况另行声明。

```powershell
$root = Join-Path (Get-Location).Path '.zmevalhub\acceptance\p03c_real'
uv run zmeval pair-captures "$root\baseline-capture" "$root\candidate-capture" --policy '.\config\gates\agent_regression_v1.json' --allow-difference model_id --bundle-dir "$root\bundles"
$LASTEXITCODE
uv run zmeval compare "$root\bundles\baseline.json" "$root\bundles\candidate.json" --allow-difference model_id
```

`pair-captures` 输出 `comparison`、`gate` 和两个标准 `EvalBundle` 路径；只有两个 bundle 文件确实生成后才执行最后一条 `compare` 命令。退出码 `0=PASS`、`1=FAIL`、`2=BLOCKED`。原始 `source_execution_log.json`、采集事件、证明、运行开始元数据和快照均在各自 capture 目录。两次运行若无受控 seed，或快照/条件不一致，应得到 BLOCKED；这是可信边界内的预期结果。
