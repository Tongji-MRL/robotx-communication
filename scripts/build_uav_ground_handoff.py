"""Build the Windows handoff Word document (requires python-docx).

Render and visually inspect the resulting document before distribution.
"""
from pathlib import Path
import json
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables'
OUT.mkdir(exist_ok=True)
DOC = OUT / 'RobotX_UAV_Ground_Test_Windows_20261107.docx'
SHA = '8fc09f295fe266ad8106cc0344a3e4d57f844359'
CHECKS = json.loads((OUT / 'uav_ground_validation_checks.json').read_text(encoding='utf-8'))
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)
sec.top_margin = sec.bottom_margin = Inches(.65)
sec.left_margin = sec.right_margin = Inches(.7)

def font(style, name='Microsoft YaHei', size=10.5, bold=False):
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = False
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'Microsoft YaHei')

for name in ['Normal', 'Body Text', 'List Bullet', 'List Number']:
    font(doc.styles[name])
    doc.styles[name].paragraph_format.space_after = Pt(6)
    doc.styles[name].paragraph_format.line_spacing = 1.12
for name, size in [('Title', 23), ('Subtitle', 11), ('Heading 1', 16), ('Heading 2', 12)]:
    font(doc.styles[name], size=size, bold=name != 'Subtitle')
    doc.styles[name].paragraph_format.space_after = Pt(8)
    doc.styles[name].paragraph_format.space_before = Pt(8 if name != 'Title' else 0)
    doc.styles[name].paragraph_format.keep_with_next = True
code_style = doc.styles.add_style('Command', 1)
font(code_style, 'Consolas', 9)
code_style.paragraph_format.line_spacing = 1.0
code_style.paragraph_format.space_before = Pt(4)
code_style.paragraph_format.space_after = Pt(7)
code_style.paragraph_format.left_indent = Inches(.09)
code_style.paragraph_format.right_indent = Inches(.06)
code_style.paragraph_format.keep_together = True
for style in doc.styles:
    if style.type == 1:
        pp = style.element.get_or_add_pPr()
        for old in list(pp.findall(qn('w:pBdr'))):
            pp.remove(old)
        snap = OxmlElement('w:snapToGrid'); snap.set(qn('w:val'), '0'); pp.append(snap)

def p(text='', style=None):
    return doc.add_paragraph(text, style)

def h(text, level=1):
    doc.add_heading(text, level)

def code(text):
    para = p(text.strip('\n'), 'Command')
    shd = OxmlElement('w:shd'); shd.set(qn('w:fill'), 'F4F5F7')
    para._p.get_or_add_pPr().append(shd)
    return para

def bullet(text):
    return p(text, 'List Bullet')

def link(label, url):
    para = p()
    rel = para.part.relate_to(url, RT.HYPERLINK, is_external=True)
    el = OxmlElement('w:hyperlink'); el.set(qn('r:id'), rel)
    run = OxmlElement('w:r'); props = OxmlElement('w:rPr')
    color = OxmlElement('w:color'); color.set(qn('w:val'), '155A8A'); props.append(color)
    run.append(props); text = OxmlElement('w:t'); text.text = label; run.append(text)
    el.append(run); para._p.append(el)

def page(title):
    doc.add_page_break()
    h(title)

def table(headers, rows, widths):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, w in enumerate(widths):
        t.columns[i].width = Inches(w)
    for i, value in enumerate(headers):
        t.rows[0].cells[i].text = value
    for row in rows:
        for c, value in zip(t.add_row().cells, row):
            c.text = str(value)
    for ri, row in enumerate(t.rows):
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement('w:cantSplit'))
        if ri == 0:
            trpr.append(OxmlElement('w:tblHeader'))
        for ci, cell in enumerate(row.cells):
            cell.width = Inches(widths[ci])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr = cell._tc.get_or_add_tcPr()
            borders = OxmlElement('w:tcBorders')
            for side in ['top', 'left', 'bottom', 'right']:
                el = OxmlElement('w:' + side)
                for key, val in [('val','single'), ('sz','4'), ('color','D9D9D9')]:
                    el.set(qn('w:' + key), val)
                borders.append(el)
            tcpr.append(borders)
            margins = OxmlElement('w:tcMar')
            for side in ['top', 'left', 'bottom', 'right']:
                el = OxmlElement('w:' + side); el.set(qn('w:w'), '95'); el.set(qn('w:type'), 'dxa'); margins.append(el)
            tcpr.append(margins)
            shd = OxmlElement('w:shd'); shd.set(qn('w:fill'), 'DCE6F1' if ri == 0 else ('F6F7F8' if ri % 2 == 0 else 'FFFFFF')); tcpr.append(shd)
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                para.paragraph_format.line_spacing = 1.0
                for run in para.runs:
                    run.font.size = Pt(9.5)
                    run.font.bold = ri == 0

# Page numbers matter when collaborators refer to a specific procedure.
footer = sec.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('RobotX UAV Ground Test  |  ')
fld = OxmlElement('w:fldSimple'); fld.set(qn('w:instr'), 'PAGE'); footer._p.append(fld)
for r in footer.runs:
    r.font.size = Pt(8)

p('RobotX UAV 地面通信测试交接手册', 'Title')
p('Windows OCS 直接 ROS 2 接入与官方 RoboCommand 模拟服务', 'Subtitle')
p('交接版本 2026 11 07 第二版    同一入口按 scenario 切换测试')
p('本手册供协作者从环境检查开始，完成真实 UAV 状态接入、Course 接收、单机运行声明、连续 Heartbeat，以及官方模拟端的有效声明、越界和超高测试。按页顺序操作，每一步都有预期结果。')
h('1 分工和测试范围')
table(['设备', '运行内容', '前提'], [
    ['电脑 A  Windows OCS', '本交接包中的 uav_ground_validation.py', '沿用已经测通 UAV topic 的 ROS 2 终端'],
    ['电脑 B  外部模拟端', 'Docker Desktop 中的 Mosquitto 和官方 test_server.py', '启用 Linux containers，A 可访问 B 的 TCP 1883'],
    ['UAV Orin', '现有真实状态发布节点', '持续发布 std_msgs/msg/String JSON；不改 topic'],
], [1.4, 2.65, 2.75])
code('UAV Orin -- ROS 2 / DDS --> Windows OCS\nWindows OCS -- MQTT / Protobuf --> B:1883\nMosquitto Broker <--> 官方 test_server.py')
p('电脑 A 和 B 可以是同一台 Windows 电脑，此时 Broker IP 用 127.0.0.1；分开部署时填写 B 的实际 IP。只有 A 需要接入 UAV 的 DDS 网络，B 不需要 ROS 2。')
table(['参数', '本次约定'], [
    ['ROS topic', '/tongji_mrl/tsky/uav_status'],
    ['来源 ID 和对外 ID', '均为 UAV1；对外声明和报告本次替代 T-Sky'],
    ['Team 和声明高度', 'TONG；依据 Course 生成围栏；声明 40 m HAE，上限 50 m HAE'],
], [2.0, 4.8])
p('官方模拟服务以 UAV 前缀识别 UAV；声明和报告统一使用 UAV1 即可触发其围栏与高度校验。该名称仅为本次测试约定，不改变 ROS topic，也不代表已经确定现场注册身份。')
p('负例测试修改的是 RunDeclaration 中的围栏或最高高度，不要求无人机真实飞出边界、飞高或伪造实际 GPS。模拟服务没有 MDF 页面，也不完成 Garuda 放行或现场验收。')

page('2 在电脑 B 准备官方模拟服务')
p('本页使用 Windows PowerShell。先按 Docker 官方 Windows 安装说明安装并启动 Docker Desktop，选择 Linux containers。首次拉取镜像需要网络；离线测试应提前完成构建。')
code('docker version\ndocker compose version\ndocker info --format "{{.OSType}}"')
p('预期：docker version 同时显示 Client 和 Server；最后一条输出 linux。如果显示无法连接 Docker engine，先启动 Docker Desktop，等引擎就绪。')
h('获取并固定官方版本', 2)
p('需要 Git for Windows。以下目录为示例，可改为实际空目录；不要把官方仓库与 OCS 交接包解压到同一个目录。')
code(fr'''New-Item -ItemType Directory -Force C:\RobotX | Out-Null
Set-Location C:\RobotX
git clone https://github.com/robonation/robocommand.git
Set-Location .\robocommand
git checkout {SHA}
Set-Location .\RobotX_2026
docker compose up -d --build
docker compose ps
docker compose logs --tail 60 rc-test''')
p('预期：broker 和 rc-test 都为运行状态，端口映射包含 1883；rc-test 日志出现 Connected、Published RxCourse (retained)。此版本发布 Course ALPHA 和 Transit A。若任一命令失败，先解决错误再继续。')
code('docker compose run --rm --no-deps rc-test python test_client.py `\n  --broker broker --port 1883 receive-course')
p('预期：打印 RxCourse 的 course_id、corners 和 uav_transit_area。这里 broker 是 Docker 内部服务名；电脑 A 要使用 B 的 IP，不能把 broker 填进 OCS 配置。')
h('记录网络地址', 2)
code('Get-NetIPConfiguration\nGet-NetTCPConnection -LocalPort 1883 -State Listen')
p('把 B 在测试网中的 IPv4 地址交给 A。示例约定 B=192.168.1.20、A=192.168.1.10，必须替换为实际地址。只在受控实验室网络开放匿名测试 Broker。')
p('如 Windows 防火墙阻止 A 访问，可在 B 的管理员 PowerShell 中添加仅允许 A 的规则。示例地址须替换；不需要关闭整个防火墙。')
code('New-NetFirewallRule -DisplayName "RobotX lab MQTT from OCS" `\n  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1883 `\n  -RemoteAddress 192.168.1.10 -Profile Private')
p('本页命令均在官方仓库 RobotX_2026 目录执行。后续每次重启或查看服务，也先进入该目录。')

page('3 在电脑 A 准备 Windows ROS 2 环境')
p(r'解压随文交接包到 C:\RobotX，得到 C:\RobotX\robotx-communication。使用与本文档配套的代码，帮助中应有 --scenario 参数。交接包不含 Python、ROS 2 或 Docker 镜像。')
p('打开原来已测通 UAV topic 的 PowerShell，按原有方法加载 ROS 2 setup 和工作区 overlay。沿用 ROS_DOMAIN_ID、RMW_IMPLEMENTATION 和网卡配置；不要换成未加载 ROS 的新终端。若原先只在 cmd 中测试过，请先用相同安装提供的 PowerShell setup 环境验证下列导入。')
code(r'''Set-Location C:\RobotX\robotx-communication
$RosPython = (Get-Command python).Source
& $RosPython -c "import sys,rclpy; from std_msgs.msg import String; print(sys.executable); print(sys.version); assert sys.version_info >= (3,10)"
Get-Item Env:ROS_DOMAIN_ID,Env:RMW_IMPLEMENTATION -ErrorAction SilentlyContinue
ros2 topic type /tongji_mrl/tsky/uav_status
ros2 topic info /tongji_mrl/tsky/uav_status --verbose
ros2 topic echo /tongji_mrl/tsky/uav_status''')
p('预期：Python 能导入 rclpy、std_msgs，版本至少 3.10；topic 类型为 std_msgs/msg/String；echo 持续显示包含 vehicle_id=UAV1 的 JSON。查看后按 Ctrl+C 结束 echo。订阅要求 RELIABLE、VOLATILE、depth=10，发布 QoS 必须兼容。')
p('如果当前 Windows ROS 绑定的是 Python 3.8/3.9，本交接包的 protobuf 7.35 无法安装；不能仅换一个新 Python 就认为 rclpy 可用。先解决 ROS 与 Python 的版本匹配，再继续本页。')
h('创建继承 ROS 包的专用环境', 2)
code(r'''& $RosPython -m venv --system-site-packages .venv-ground
$GroundPython = Join-Path $PWD '.venv-ground\Scripts\python.exe'
& $GroundPython -m pip install -r .\OCS\requirements.txt
& $GroundPython -c "import rclpy,paho.mqtt.client,google.protobuf; from std_msgs.msg import String; print(google.protobuf.__version__)"
& $GroundPython .\OCS\uav_ground_validation.py --help
ros2 topic hz /tongji_mrl/tsky/uav_status''')
p('预期：protobuf 显示 7.35.x；帮助中包含 --vehicle-id、--scenario；topic 持续更新，已测链路常用约 5 Hz。观察后 Ctrl+C 结束 hz。专用环境继承已加载的 ROS 包。')
h('确认可以访问模拟端', 2)
code("$BrokerIp = '192.168.1.20'  # 改成电脑 B 的实际地址\nTest-NetConnection $BrokerIp -Port 1883")
p('预期 TcpTestSucceeded=True。A、B 同机时把 BrokerIp 设为 127.0.0.1。此 TCP 检查与 ROS topic 检查是两条独立链路，两项都通过后再启动 OCS。')

page('4 配置单 UAV 并启动 OCS')
p('在电脑 A 的同一个 ROS PowerShell 中，复制模板后编辑本机配置。路径变量 GroundPython 和 BrokerIp 沿用上一页；新终端需要重新加载 ROS 环境并重新设置这些变量。')
code(r'''Copy-Item .\OCS\config.uav-ground.example.json .\OCS\config.uav-ground.local.json
notepad .\OCS\config.uav-ground.local.json''')
p('host 改为 B 的 IP，飞手填实际标识；机身注册号可暂留空。已确认本链路来源 ID 是 UAV1；若接手时 echo 不同，只改 source_vehicle_id 以匹配原始 JSON，对外 vehicle_id 仍用 UAV1，无需修改 Orin 发布器。JSON 不接受注释。')
code('''{
  "team_id": "TONG",
  "robocommand": {"host": "192.168.1.20", "port": 1883},
  "vehicles": {
    "uav": {
      "vehicle_id": "UAV1",
      "source_vehicle_id": "UAV1",
      "uav_registration": ""
    }
  },
  "run_declaration": {
    "task_tiers": {
      "task1": "none", "task2": "none",
      "task3": "none", "task4": "none"
    },
    "uav_geofence_mode": "auto_course",
    "uav_geofence": [],
    "uav_geofence_margin_m": 2.0,
    "uav_geofence_max_altitude_hae_m": 40.0,
    "uav_geofence_altitude_limit_hae_m": 50.0,
    "uav_pilot_callsign": "YOUR-PILOT"
  }
}''')
p('auto_course 根据刚收到的 corners 生成位于 Course 内的保守候选围栏，留出 2 m 边距；它不是直接复制整个 Course，也不会把 Transit 自动并入。40/50 m 都是 HAE 椭球高，不是离地高，且不会上传到 PX4。')
code(r'''New-Item -ItemType Directory -Force .\logs | Out-Null
$RunStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario normal `
  --log ".\logs\uav-ground-$RunStamp.jsonl" `
  2>&1 | Tee-Object ".\logs\uav-ground-$RunStamp-console.log"''')
p('默认持续运行，Ctrl+C 停止。--duration 90 从程序启动开始计时，不能代替“已有有效心跳持续一分钟”的观察。不要同时启动旧 OCS/Gateway 或另一份同 Team 同车辆的心跳发布器。')

page('5 正常链路测试和通过判据')
table(['阶段', '电脑 A 的观察', '电脑 B 的观察'], [
    ['接收场地', 'WAIT_COURSE 后进入 DECLARING', '已发布 retained RxCourse'],
    ['单机声明', 'DECLARATION_PUBLISHED；只有 UAV1，四项 tier=NONE', '[geofence] TONG: UAV geofence and ceiling OK'],
    ['实际遥测', 'HEARTBEATING；HEARTBEAT_PUBLISHED 约 2 Hz', 'RxReport 的 vehicle_id=UAV1，body=heartbeat'],
    ['等待启动', '真实状态为 MANUAL 时继续报告 MANUAL', 'Tracking TONG vehicles [UAV1]，等待 AUTO'],
    ['启动通知', 'RUN_START_RECORDED；序号匹配，记录 run_id', '[auto-start] 发布匹配 declaration_seq 的 RunStart'],
], [1.0, 2.9, 2.9])
p('B 上持续观察：docker compose logs -f rc-test。Ctrl+C 只结束日志跟踪，不会停止以 -d 启动的服务。')
h('保持真实状态', 2)
p('OCS 的状态、飞行阶段、位置、速度、航向和高度来自 UAV JSON，不会自动将 MANUAL 改成 AUTO。单 UAV 下只有其真实状态上报 AUTO 才会触发 RunStart。若本轮只做 MANUAL 地面遥测，记录“RunStart 未执行”即可，不应记为失败。')
p('需要验证 RunStart 时，由 UAV 负责人按现有地面测试程序提供真实、就绪的 AUTO 状态；本入口只记录 RunStart，不发布飞行或任务命令。不要为了凑齐日志修改真实状态字段。')
h('持续观察至少一分钟', 2)
bullet('从第一条有效 Heartbeat 开始计时至少 60 秒，确认状态和数值与 ROS echo 一致；约 2 Hz，对应约 120 条心跳。')
bullet('确认报告序号按车辆持续递增，同进程重新声明也不回退。RxReport 协议没有 run_id 字段；run_id 来自 RunStart，并保存在 OCS 本地状态和 JSONL 事件中。')
bullet('保留 B 的接收日志。A 的 HEARTBEAT_PUBLISHED 只表示 Broker 已给 QoS1 PUBACK，不等于 MDF 验收。')
bullet('如进行断流测试，只暂停测试用状态发布器或其链路，不关闭飞控；超过 3 秒后 A 应出现 UAV_TELEMETRY_STALE 并停止旧心跳，新鲜有效数据恢复后继续。')
p('真实 GPS 应原样上报，模拟器不判断飞机是否在示例坐标内。无来源时间戳时仅证明 OCS 收包新鲜；采样至显示不超过 5 秒、位置误差、实机围栏一致性和 MDF 显示需现场另验。')

page('6 同一入口选择测试场景')
p('三个场景都在电脑 A 运行 uav_ground_validation.py，使用同一份正常配置和真实 ROS 状态。电脑 B 只运行官方模拟服务并观察日志，不需要换用另一个声明或心跳脚本。')
table(['scenario 参数', '发送的声明', '预期服务端结果'], [
    ['normal', '依据当前 Course 生成合法围栏；使用配置高度 40 m HAE', '接受声明；真实 AUTO 后 RunStart'],
    ['outside-course', '合法基线围栏整体移至 Course 和 Transit 北侧之外；高度仍为 40', '因围栏越界而 refused'],
    ['over-height', '保持合法基线围栏；声明最高高度改为 60 m HAE', '因最高高度而 refused'],
], [1.35, 3.35, 2.1])
p('所有场景都经过 ROS 订阅、官方连接、当前 RxCourse 校验、单 UAV 声明及真实 2 Hz Heartbeat。负例只在最后构造测试声明时改变指定字段；实际 GPS、实际高度、MANUAL/AUTO 和飞行阶段均原样转换。')
h('每例先停止 A 再重置 B', 2)
p('A 按 Ctrl+C 停止上一进程。B 在官方 RobotX_2026 目录执行：')
code('docker compose restart rc-test\ndocker compose logs --tail 30 rc-test')
p('等本次重启后的 Connected 和 Published RxCourse (retained) 出现，再在 A 启动下一例。固定官方版本保持默认 ALPHA/Transit A 和 50 m HAE 上限；负例仅连接这个隔离模拟端。')
p('示例用独立 Team GVSYS1、GVSYS2、GVSYS3，避免混淆日志。拒绝新声明不会清除旧的有效声明，不能省略重置步骤，也不能让上一份 OCS 继续发心跳。')
h('SYS1 正常声明与真实心跳', 2)
code(r'''& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario normal --team-id GVSYS1 `
  --log .\logs\sys1-normal.jsonl''')
p('本例保持运行至少一分钟有效遥测，再 Ctrl+C 结束。B 应记录 [geofence] GVSYS1: UAV geofence and ceiling OK，并持续收到 UAV1 的 Heartbeat。MANUAL 下等待是预期；真实 AUTO 时才检验匹配的 RunStart。')
p('不要把 local.json 改成非法围栏或 60 m；正常模式仍会本地拒绝它们。下一页通过显式 scenario 参数产生负例，不改基线配置。')

page('7 同一入口运行越界和超高测试')
h('SYS2 围栏超出 Course 和 Transit', 2)
p('按上一页停止 A 并重启 B 后，在 A 的 ROS PowerShell 运行：')
code(r'''& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario outside-course --team-id GVSYS2 `
  --outside-offset-m 20 --duration 90 `
  --log .\logs\sys2-outside-course.jsonl''')
p('程序先校验合法基线，再按本次收到的 Course 和 Transit 范围，把整个声明围栏移到二者最北边界之外至少 20 m。首尾仍闭合；高度仍取正常配置。参数范围 2 至 100000 m，高于官方 1 m 容差；不使用固定经纬度负例。')
code('RunDeclaration for GVSYS2 refused:\nuav_geofence leaves the course and transit area by ...')
p('通过判据：B 日志明确给出 GVSYS2 的越界 refused；A 记录实际发送的测试围栏，同时继续转发真实 UAV 心跳。实际位置不能随声明围栏一起移动。')
h('SYS3 声明最高高度超过限制', 2)
p('再次停止 A、重启 B 并等 Course 就绪，然后在 A 运行：')
code(r'''& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario over-height --team-id GVSYS3 `
  --test-max-altitude-hae 60 --duration 90 `
  --log .\logs\sys3-over-height.jsonl''')
p('只把声明最高高度改为 60 m HAE；围栏、飞手、车辆、四项 NONE 和实际 Heartbeat 高度保持各自原始值。测试高度必须在 protobuf 实际编码后仍超过官方示例的 50 m HAE 上限。')
code('RunDeclaration for GVSYS3 refused:\nuav_geofence_max_altitude_hae_m is 60: it must be above 0 and at most 50')
h('运行完成不等于拒绝验证通过', 2)
p('官方拒绝只记日志，没有拒绝回包。A 的发布成功和退出码 0 只表示通信执行完成；负例结束仍标记 acceptance_unknown，必须用 B 的明确 refused 日志判定。没有 RunStart 不能单独证明拒绝。')
p('负例收到匹配 RunStart 会记录 SCENARIO_FAILED 并退出，不能按正常运行继续；声明之后发生断线或场地变化也会退出，重置服务后再测，避免自动重发污染结果。三种模式均不发布车辆或飞行命令。')

page('8 保存证据和结束测试')
h('电脑 B 每例保存一次', 2)
code(r'''New-Item -ItemType Directory -Force .\evidence | Out-Null
$Case = 'SYS2'  # 当前案例改为 NORMAL、SYS1、SYS2 或 SYS3
$CaseStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
docker compose logs --no-color rc-test |
  Set-Content -Encoding utf8 ".\evidence\$Case-$CaseStamp.log"
git rev-parse HEAD | Set-Content .\evidence\official-commit.txt
docker compose ps | Out-File .\evidence\compose-status.txt''')
p(r'官方服务也会在 RobotX_2026\logs 下自动生成带时间戳的日志。每例结束后立即保存，重启记录和旧案例可能同时出现在 compose logs 中；判读时按 Team、启动时间和本次请求定位。')
h('电脑 A 保存真实链路记录', 2)
bullet('保存 logs 中本轮 JSONL 和 console.log；后者包含 Course 和声明围栏等输出。')
bullet('保存本机配置副本、真实 source_vehicle_id、外发 vehicle_id、Python 与 ROS 版本、ROS_DOMAIN_ID、RMW、A/B IP 和测试起止时间。共享前移除不需要公开的注册号或个人信息。')
bullet('记录本轮是 MANUAL 遥测，还是已实测 AUTO 到 RunStart；如后者，记录 declaration_seq 和 run_id。')
h('统一结果记录', 2)
table(['案例', '必备证据', '结果填写'], [
    ['正常真实链路', 'RxCourse、单 UAV 声明、ROS 与 Heartbeat 字段一致、至少 60 s 接收日志', '通过  失败  未执行'],
    ['真实 RunStart', '真实 AUTO、匹配 declaration_seq、A 记录 run_id；无车辆命令', '通过  失败  未执行'],
    ['断流恢复', '超过 3 s 停止旧心跳；新鲜数据恢复后继续', '通过  失败  未执行'],
    ['SYS1', 'normal 模式；GVSYS1 的 geofence OK 和真实心跳', '通过  失败  未执行'],
    ['SYS2', 'GVSYS2 的明确越界 refused 原因', '通过  失败  未执行'],
    ['SYS3', 'GVSYS3 的明确高度 refused 原因', '通过  失败  未执行'],
], [1.25, 4.0, 1.55])
h('关闭和重新开始', 2)
p('先在 A 停止 OCS，再在 B 执行下列命令。down 不会删除主机 logs 目录。下一轮先启动 B，再启动 A，避免服务器重置序号而旧 OCS 仍保留上轮 run_id。')
code('docker compose down')

page('9 常见问题和版本依据')
table(['现象', '检查与处理'], [
    ['导入 rclpy 失败', '回到已测通的 ROS 终端。确认 GroundPython 来自继承该环境的 .venv-ground；不要使用旧 .venv。'],
    ['protobuf 安装失败', '先检查 Python >=3.10；ROS 二进制绑定必须匹配该解释器。保持 paho-mqtt 2.0.0、protobuf 7.35。'],
    ['topic 可见但收不到状态', '检查 ROS_DOMAIN_ID、网卡、RMW 和 QoS；本入口订阅 String、RELIABLE/VOLATILE。'],
    ['UAV_REJECTED', '核对来源 ID UAV1、必需 JSON 字段、MANUAL/AUTO/KILLED、GROUNDED/AIRBORNE、HAE 单位；来源时间戳需新鲜。'],
    ['WAIT_ROBOCOMMAND', '检查 B 的 Docker 引擎、1883 端口映射、实际 IP、防火墙和 Test-NetConnection。'],
    ['WAIT_COURSE', 'Broker 连接不等于 test_server 已工作；查看 rc-test 日志及 receive-course。'],
    ['声明接受但没有 RunStart', '只声明 UAV1，且同 ID 心跳必须为 AUTO；MANUAL 下等待是预期。'],
    ['越界负例竟被接受', '检查声明 vehicle_ids 是否为 UAV1；T-Sky 不进入该官方版本的 UAV 校验分支。'],
    ['本地先报围栏或高度错误', '先恢复合法基线配置；负例用 A 上同一入口的 --scenario 参数，不能改坏 local.json。'],
], [1.85, 4.95])
h('本交接包的验证范围', 2)
p(f"交接前通过 {CHECKS['full_ocs_suite']['tests']} 项 OCS 回归，四条 loopback MQTT 流程及三种实际构造声明的官方校验逻辑均已验证；记录见包内 VALIDATION.txt。真实跨机 DDS、Docker 部署和 MDF 尚未实测，由协作者按本手册记录结果。")
h('源码与安装参考', 2)
p('官方固定提交：' + SHA)
link('官方测试工具及启动说明', 'https://github.com/robonation/robocommand/tree/' + SHA + '/RobotX_2026')
link('服务器围栏与高度校验及 RunStart 逻辑', 'https://github.com/robonation/robocommand/blob/' + SHA + '/RobotX_2026/rc_test/test_server.py#L162-L246')
link('客户端声明构造和命令参数', 'https://github.com/robonation/robocommand/blob/' + SHA + '/RobotX_2026/rc_test/test_client.py')
link('Docker Desktop Windows 安装说明', 'https://docs.docker.com/desktop/setup/install/windows-install/')

doc.core_properties.title = 'RobotX UAV 地面通信测试交接手册'
doc.core_properties.subject = 'Windows ROS 2 OCS 与官方 RoboCommand 模拟服务配置和测试'
doc.core_properties.author = 'Tongji RobotX'
doc.core_properties.keywords = 'RobotX UAV ROS2 RoboCommand Ground Validation'
doc.save(DOC)
print(DOC)
