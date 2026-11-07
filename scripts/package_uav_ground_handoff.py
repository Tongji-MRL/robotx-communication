"""Package and verify the curated ground-test handoff.

Run with a Python containing python-docx; --python selects the interpreter
with OCS runtime dependencies for the isolated package test suite.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from docx import Document

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--python', type=Path, default=Path(sys.executable))
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
scratch=Path(tempfile.gettempdir())/'robotx-ground-handoff-20261107'
scratch.mkdir(exist_ok=True)
checks=json.loads((root/'deliverables/uav_ground_validation_checks.json').read_text(encoding='utf-8'))
stage=Path(tempfile.mkdtemp(prefix='robotx-ground-package-'))/'robotx-communication'
stage.mkdir()
runtime=['uav_ground_validation.py','ocs_client.py','uav_status.py','course_store.py',
         'course_config.py','geofence_planner.py','heartbeat_cache.py']
tests=['test_uav_ground_validation.py','test_ros2_ground_input.py','test_ground_mqtt_flow.py','test_ground_scenarios.py',
       'test_geofence_planner.py','test_course_store.py']
files=[root/'OCS'/x for x in runtime+tests+['requirements.txt','config.uav-ground.example.json']]
files += [root/'scripts/start_uav_ground_validation.bat']
files += sorted((root/'RobotX_2026/gen/python').rglob('*.py'))
files += sorted((root/'RobotX_2026/gen/python').rglob('*.pyi'))
for source in files:
    rel=source.relative_to(root)
    target=stage/rel; target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
manual=root/'deliverables/RobotX_UAV_Ground_Test_Windows_20261107.docx'
(stage/'docs').mkdir()
shutil.copy2(manual,stage/'docs'/manual.name)
(stage/'README_FIRST.txt').write_text('''RobotX UAV Windows ground-test handoff 2026-11-07

先阅读 docs/RobotX_UAV_Ground_Test_Windows_20261107.docx。
解压此包到 C:\\RobotX，得到 C:\\RobotX\\robotx-communication。
本包为文档第二版配套代码快照，文件内容以 FILES_SHA256.txt 为准。
仅包含单 UAV 地面通信入口、配置、必要模块、官方生成的 schema 和相关测试。
外发 ID 默认 UAV1；ROS JSON 来源默认 UAV1；ROS topic 不变。
同一入口 --scenario normal / outside-course / over-height，负例仍转发真实 ROS 心跳。
Windows OCS 须在已测通的 ROS 2 环境运行；Python >=3.10。
不包含 ROS 2、Python、Docker 引擎、Docker 镜像或真实设备配置。
电脑 B 按手册单独下载并固定官方 robocommand 仓库版本。
不要在此 OCS 包的 RobotX_2026 目录执行 docker compose；它只包含 schema。
官方 Compose 文件位于单独的 robocommand/RobotX_2026 目录。

可选离线测试：
在 OCS 包根目录，用装有 requirements.txt 的 Python 执行：
python -m unittest discover -s OCS -p "test_*.py"
这些测试不连接真实 UAV 或官方服务器；四条集成流程使用本机 loopback MQTT。
测试范围及限制见 VALIDATION.txt；文件完整性见 FILES_SHA256.txt。
''',encoding='utf-8-sig')

# Test the actual curated files, independent of the source checkout.
py=args.python.resolve()
script="""import contextlib,io,unittest,sys,json
sys.path.insert(0,'OCS')
b=io.StringIO()
s=unittest.defaultTestLoader.discover('OCS',pattern='test_*.py')
with contextlib.redirect_stdout(b),contextlib.redirect_stderr(b):
 r=unittest.TextTestRunner(stream=b).run(s)
print(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped)}))
if not r.wasSuccessful(): print(b.getvalue())
sys.exit(not r.wasSuccessful())
"""
result=subprocess.run([str(py),'-c',script],cwd=stage,capture_output=True,text=True,encoding='utf-8',errors='replace')
print(result.stdout)
if result.returncode:
    print(result.stderr); raise SystemExit(result.returncode)
counts=json.loads(result.stdout.strip())
help_result=subprocess.run([str(py),'OCS/uav_ground_validation.py','--help'],cwd=stage,capture_output=True,text=True)
assert help_result.returncode==0 and '--scenario' in help_result.stdout

(stage/'VALIDATION.txt').write_text(f'''验证日期 2026-11-07
完整原始仓库 OCS 回归：{checks['full_ocs_suite']['tests']} 项通过，0 失败，0 错误，0 跳过。
本交接包独立目录回归：{counts['tests']} 项通过，0 失败，0 错误，0 跳过。
本交接包入口 --help 导入和 --scenario 参数检查通过。
包内回归是完整仓库回归的子集；没有包含其他 USV/UI 组件。

官方版本：8fc09f295fe266ad8106cc0344a3e4d57f844359
以当前 GroundValidationSession.prepare_declaration 实际产生的声明，
调用官方 test_server.py 的 geofence_problems 离线验证：
normal：当前 Course 生成的合法闭合围栏，40 m HAE，接受。
outside-course：仅平移围栏至 Course 和 Transit 北侧之外，拒绝；高度仍40。
over-height：合法基线围栏不变，最高高度60 m HAE，拒绝；上限50。
四条 MQTT 集成流程：正常、越界、超高、负例意外 RunStart 导致退出。
正常重连重新声明后 report_seq 为 1、2、3，保持递增。
对外 ID 使用 UAV1 进入官方 UAV 校验分支。

实际 MQTT socket 验证使用本机轻量 loopback broker 和 Mock ROS 输入；
订阅类型、topic、QoS 和生命周期以假的 rclpy 模块验证。
未实测真实 ROS 2 / DDS、跨机网络、Docker 容器、RoboCommand/MDF 或飞行硬件。
文档中的 Windows PowerShell 命令按语法解析检查；安装和现场执行由协作者完成。
Word 文档已由 Microsoft Word 导出并逐页视觉检查。

此包代表文档第二版配套代码；SHA256 清单可与远端提交逐项核对。
源码来源 https://github.com/Tongji-MRL/robotx-communication
''',encoding='utf-8-sig')

# Remove generated __pycache__ only from the file selection, never delete paths.
pack_files=sorted(p for p in stage.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
manifest='\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(stage).as_posix() for p in pack_files)+'\n'
(stage/'FILES_SHA256.txt').write_text(manifest,encoding='utf-8')
pack_files.append(stage/'FILES_SHA256.txt')
archive=root/'deliverables/RobotX_UAV_Ground_Test_Windows_20261107_handoff.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for p in pack_files:
        z.write(p,'robotx-communication/'+p.relative_to(stage).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for line in manifest.splitlines():
        digest,rel=line.split('  ',1)
        assert hashlib.sha256(z.read('robotx-communication/'+rel)).hexdigest()==digest
print('archive',archive,'bytes',archive.stat().st_size,'files',len(pack_files))
print('stage',stage)
scratch.joinpath('package-stage.txt').write_text(str(stage),encoding='utf-8')

# Copy the literal Word command text for syntax-only PowerShell validation.
blocks=[]
for para in Document(manual).paragraphs:
    if para.style.name=='Command' and para.text.startswith(('docker ','New-Item ','New-NetFirewallRule ', 'Get-NetIPConfiguration', 'Set-Location ', '& $RosPython', '& $GroundPython', '$BrokerIp', 'Copy-Item ')):
        blocks.append(para.text)
scratch.joinpath('powershell-commands.json').write_text(json.dumps(blocks,ensure_ascii=False),encoding='utf-8-sig')
print('PowerShell blocks',len(blocks))
