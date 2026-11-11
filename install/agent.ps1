# TRACE 진단 에이전트 한 줄 설치·실행 (Windows PowerShell 5.1·7)
#
#   & ([scriptblock]::Create((irm https://gakdo.site/agent.ps1))) 123456
#
# 하는 일: 에이전트 소스를 GitHub에서 받아 %LOCALAPPDATA%\trace-agent에 풀고(실행 의존성 jsonschema는 python -m pip --target으로 lib에, pypi.org가 막히면 카카오 미러),
# TRACE_API_URL을 채워 `python -m trace_agent run --code <코드>`를 실행한다. python.exe로 모듈을 부르므로
# 스마트 앱 컨트롤이 서명 없는 trace-agent.exe를 막아도 돈다. 파이썬이 없으면 nuget.org의 공식 zip을 받아 쓴다
# (학교 망은 python.org·pypi.org를 막는다). 결과를 보여 주고 y를 넣어야 올린다. 비밀값은 이 파일에 없다.
#
# 바꿀 수 있는 값(환경 변수): TRACE_API_URL(기본 https://gakdo.site), TRACE_AGENT_REF(브랜치나 태그, 기본 v0.2.0. 최신 개발본은 develop),
# TRACE_AGENT_HOME(기본 %LOCALAPPDATA%\trace-agent), TRACE_AGENT_SRC(소스 zip 주소), TRACE_CODE(인자 대신 코드)
param([string]$Code = $env:TRACE_CODE)

function Invoke-TraceAgent([string]$Code) {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'  # 5.1은 진행 표시 때문에 다운로드가 몹시 느려진다
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

  $api = if ($env:TRACE_API_URL) { $env:TRACE_API_URL } else { 'https://gakdo.site' }
  $ref = if ($env:TRACE_AGENT_REF) { $env:TRACE_AGENT_REF } else { 'v0.2.0' }
  $home_ = if ($env:TRACE_AGENT_HOME) { $env:TRACE_AGENT_HOME } else { Join-Path $env:LOCALAPPDATA 'trace-agent' }
  $src = if ($env:TRACE_AGENT_SRC) { $env:TRACE_AGENT_SRC } else { "https://codeload.github.com/GAKDO/agent/zip/$ref" }

  if ($Code -and $Code -notmatch '^\d{6}$') {
    Write-Host '페어링 코드는 6자리 숫자예요.' -ForegroundColor Red
    return
  }
  New-Item -ItemType Directory -Force -Path $home_ | Out-Null

  # 파이썬 3.11 이상 찾기. WindowsApps의 python.exe는 스토어로 보내는 가짜라 버전 검사에서 걸러진다
  $py = $null
  $candidates = @(
    @{ exe = (Join-Path $home_ 'python\tools\python.exe'); args = @() },
    @{ exe = 'py'; args = @('-3.12') }, @{ exe = 'py'; args = @('-3.11') }, @{ exe = 'py'; args = @('-3.13') },
    @{ exe = 'python'; args = @() }
  )
  foreach ($c in $candidates) {
    try {
      & $c.exe @($c.args + @('-c', 'import sys; sys.exit(sys.version_info < (3, 11))')) 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
  }
  if (-not $py) {
    Write-Host '파이썬 3.11 이상이 없어 nuget.org에서 파이썬 3.12를 받아요(설치 없이 이 폴더에만 풀어요)...'
    $zip = Join-Path $env:TEMP 'trace-python.zip'
    Invoke-WebRequest -UseBasicParsing 'https://www.nuget.org/api/v2/package/python/3.12.10' -OutFile $zip
    $dest = Join-Path $home_ 'python'
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Remove-Item $zip -Force
    $py = @{ exe = (Join-Path $dest 'tools\python.exe'); args = @() }
  }

  Write-Host "에이전트를 받는 중이에요 ($ref)..."
  $tmp = Join-Path $env:TEMP ('trace-agent-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  try {
    $zip = Join-Path $tmp 'agent.zip'
    Invoke-WebRequest -UseBasicParsing $src -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $new = Get-ChildItem -Directory $tmp | Select-Object -First 1
    if (-not $new -or -not (Test-Path (Join-Path $new.FullName 'src\trace_agent\__main__.py'))) {
      Write-Host "받은 파일에 에이전트가 없어요: $src" -ForegroundColor Red
      return
    }
    $dstSrc = Join-Path $home_ 'src'
    if (Test-Path $dstSrc) { Remove-Item -Recurse -Force $dstSrc }
    Move-Item (Join-Path $new.FullName 'src') $dstSrc
    # PS 5.1은 외부 명령 인자 속 큰따옴표를 망가뜨리므로 파이썬 코드에 작은따옴표만 쓴다
    $pyproject = Join-Path $new.FullName 'pyproject.toml'
    $deps = @(& $py.exe @($py.args + @('-c', 'import sys, tomllib; print(chr(10).join(tomllib.load(open(sys.argv[1], ''rb''))[''project''][''dependencies'']))', $pyproject)) |
      Where-Object { $_ })
  } finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
  }

  # 실행 의존성(pyproject.toml의 dependencies, 지금은 jsonschema)을 lib에 받는다. 이미 있으면 건너뛴다.
  # pip.exe 대신 python -m pip(스마트 앱 컨트롤). 학교 망은 pypi.org를 막으므로 안 되면 카카오 미러로 다시 받는다
  $lib = Join-Path $home_ 'lib'
  # PS 5.1은 Stop일 때 외부 명령의 stderr를 2>$null로 돌려도 종료 오류로 바꾼다. 이 구간은 종료 코드로만 판단한다
  $ErrorActionPreference = 'Continue'
  $oldPath = $env:PYTHONPATH
  $env:PYTHONPATH = $lib
  & $py.exe @($py.args + @('-c', 'import jsonschema, referencing')) 2>$null | Out-Null
  $haveDeps = ($LASTEXITCODE -eq 0)
  $env:PYTHONPATH = $oldPath
  if ($deps.Count -gt 0 -and -not $haveDeps) {
    Write-Host "필요한 패키지를 받는 중이에요: $($deps -join ' ')"
    if (Test-Path $lib) { Remove-Item -Recurse -Force $lib }
    $pipArgs = @('-m', 'pip', 'install', '-q', '--disable-pip-version-check', '--target', $lib)
    & $py.exe @($py.args + $pipArgs + @('--timeout', '10', '--retries', '1') + $deps) 2>$null
    if ($LASTEXITCODE -ne 0) {
      Write-Host 'pypi.org에 닿지 않아 카카오 미러로 다시 받아요...'
      if (Test-Path $lib) { Remove-Item -Recurse -Force $lib }
      & $py.exe @($py.args + $pipArgs + @('-i', 'https://mirror.kakao.com/pypi/simple') + $deps)
      if ($LASTEXITCODE -ne 0) {
        Write-Host "패키지를 받지 못했어요: $($deps -join ' ')" -ForegroundColor Red
        return
      }
    }
  }
  $ErrorActionPreference = 'Stop'

  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $admin) {
    Write-Host '참고: 관리자 권한 PowerShell이 아니라 SSD 수명 값은 "생략"으로 남아요.' -ForegroundColor Yellow
  }

  $oldApi = $env:TRACE_API_URL; $oldPath = $env:PYTHONPATH
  $env:TRACE_API_URL = $api
  $env:PYTHONPATH = (Join-Path $home_ 'src') + ';' + $lib
  Push-Location $home_  # 진단 JSON은 이 폴더에 남는다(못 올렸을 때 다시 올리기용)
  try {
    $agentArgs = @('-m', 'trace_agent', 'run')
    if ($Code) { $agentArgs += @('--code', $Code) }
    & $py.exe @($py.args + $agentArgs)
  } finally {
    Pop-Location
    $env:TRACE_API_URL = $oldApi; $env:PYTHONPATH = $oldPath
  }
}

Invoke-TraceAgent $Code
