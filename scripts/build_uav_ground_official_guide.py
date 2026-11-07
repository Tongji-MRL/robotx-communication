"""Build the TONG live RoboCommand ground-validation Word guide.

Uses python-docx. Render and inspect every page before distributing the DOCX.
The original Docker simulation guide remains a separate document.
"""
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables'
DOC = OUT / 'RobotX_TONG_Ground_Validation_Official_20261107.docx'
SHA = '8fc09f295fe266ad8106cc0344a3e4d57f844359'
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
    doc.styles[name].paragraph_format.line_spacing = 1.1
for name, size in [('Title', 22), ('Subtitle', 11), ('Heading 1', 16), ('Heading 2', 12)]:
    font(doc.styles[name], size=size, bold=name != 'Subtitle')
    doc.styles[name].paragraph_format.space_after = Pt(8)
    doc.styles[name].paragraph_format.space_before = Pt(8 if name != 'Title' else 0)
    doc.styles[name].paragraph_format.keep_with_next = True
cmd = doc.styles.add_style('Command', 1)
font(cmd, 'Consolas', 9)
cmd.paragraph_format.line_spacing = 1.0
cmd.paragraph_format.space_before = Pt(4)
cmd.paragraph_format.space_after = Pt(7)
cmd.paragraph_format.left_indent = Inches(.08)
cmd.paragraph_format.right_indent = Inches(.04)
cmd.paragraph_format.keep_together = True
literal = doc.styles.add_style('Output', 1)
literal.base_style = cmd
for style in doc.styles:
    if style.type == 1:
        pp = style.element.get_or_add_pPr()
        for old in list(pp.findall(qn('w:pBdr'))):
            pp.remove(old)
        snap = OxmlElement('w:snapToGrid')
        snap.set(qn('w:val'), '0')
        pp.append(snap)


def p(text='', style=None):
    previous = doc.element.body[-2] if len(doc.element.body) > 1 else None
    para = doc.add_paragraph(text, style)
    if previous is not None and previous.tag == qn('w:tbl'):
        para.paragraph_format.space_before = Pt(6)
    return para


def h(text, level=1):
    doc.add_heading(text, level)


def page(title):
    heading = doc.add_heading(title, 1)
    heading.paragraph_format.page_break_before = True


def code(text, executable=True):
    return p(text.strip('\n'), 'Command' if executable else 'Output')


def bullet(text):
    p(text, 'List Bullet')


def table(headers, rows, widths):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, w in enumerate(widths):
        t.columns[i].width = Inches(w)
        t.rows[0].cells[i].text = headers[i]
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
                for key, val in [('val', 'single'), ('sz', '4'), ('color', 'D9D9D9')]:
                    el.set(qn('w:' + key), val)
                borders.append(el)
            tcpr.append(borders)
            margins = OxmlElement('w:tcMar')
            for side in ['top', 'left', 'bottom', 'right']:
                el = OxmlElement('w:' + side)
                el.set(qn('w:w'), '90')
                el.set(qn('w:type'), 'dxa')
                margins.append(el)
            tcpr.append(margins)
            shd = OxmlElement('w:shd')
            shd.set(qn('w:fill'), 'DCE6F1' if ri == 0 else ('F6F7F8' if ri % 2 == 0 else 'FFFFFF'))
            tcpr.append(shd)
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                para.paragraph_format.line_spacing = 1.0
                for run in para.runs:
                    run.font.size = Pt(9.5)
                    run.font.bold = ri == 0


def link(label, url):
    para = p()
    rel = para.part.relate_to(url, RT.HYPERLINK, is_external=True)
    el = OxmlElement('w:hyperlink')
    el.set(qn('r:id'), rel)
    run = OxmlElement('w:r')
    props = OxmlElement('w:rPr')
    color = OxmlElement('w:color')
    color.set(qn('w:val'), '155A8A')
    props.append(color)
    run.append(props)
    text = OxmlElement('w:t')
    text.text = label
    run.append(text)
    el.append(run)
    para._p.append(el)


footer = sec.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('RobotX TONG Ground Validation  |  ')
fld = OxmlElement('w:fldSimple')
fld.set(qn('w:instr'), 'PAGE')
footer._p.append(fld)
for run in footer.runs:
    run.font.size = Pt(8)

p('RobotX UAV 官方现场地面验证操作手册', 'Title')
p('TONG 队伍  Windows ROS 2  2026 年 11 月 7 日版', 'Subtitle')
p('本手册供 OCS 操作员、UAV 飞手和现场验收人员配合使用。目标是通过真实 ROS 2 上行，将单架 UAV 的声明与遥测送入官方 RoboCommand 和 MDF，并保存正常、越界、超高三类测试证据。按本手册直接连接现场服务，无需启动本地 Docker 或 test_server.py。')
h('1 先核对本次现场参数')
table(['项目', '本次采用的值'], [
    ['正式队伍 ID', 'TONG'],
    ['官方网络与电脑地址', '192.168.69.0/24；OCS 以太网使用 DHCP，地址范围为 192.168.69.15 至 192.168.69.254'],
    ['RoboCommand 地址', '工作人员分配 192.168.69.2 至 192.168.69.6 中的一个实例；不能默认选 .2 或用网关推断'],
    ['MQTT 端口', '1883，若现场另行更新，以现场参数为准'],
    ['UAV 身份', '本手册使用对外 UAV1，须与官方登记对应；ROS 来源 vehicle_id 仍为 UAV1'],
    ['ROS topic', '/tongji_mrl/tsky/uav_status，类型 std_msgs/msg/String，data 为 JSON'],
], [1.45, 5.35])
h('现场填写后再启动', 2)
p('RoboCommand IP ____________________    OCS DHCP IP ____________________\n飞手 first name ____________________    CAAS 贴纸原号码 ____________________\n正式注册字符串 TONG-____________________\nSV 区域或批准围栏记录 ____________________\n声明最高高度 __________ m HAE    适用上限 __________ m HAE')
h('执行顺序与职责', 2)
p('检查 DHCP 与端口 → 插着官方网线复查 ROS → 填写身份和合法围栏 → 启动 normal → 接收 RxCourse → 自动发送 RunDeclaration → 持续真实心跳 → 在 MDF 验收 → 按考官安排执行 SYS2 和 SYS3。')
p('本入口收到合法 Course 后即自动提交声明，不等待人工确认。它只记录 RunStart，不向飞机发送 Course、围栏、起飞或任务命令。机载围栏加载与飞控操作由原有 UAV 系统和飞手完成。')

page('2 接入官方网络并检查连通性')
p('在 Windows 中选择实际连接官方 RJ45 网线的以太网接口，将 IPv4 和 DNS 都设为自动获取。该接口关闭 Internet 连接共享、网络桥接和 DHCP 服务。保留已经测通的 UAV 内网接口；只有一个网口时，需另一个网卡或已测通的无线链路保持两边同时可达。')
code('''Get-NetAdapter
ipconfig /all''')
p('预期：官方网卡为 Up，DHCP 已启用，IPv4 为 192.168.69.15 至 254，掩码 255.255.255.0。169.254.x.x 通常说明未获得 DHCP 租约。比赛网络不提供互联网，Windows 显示无 Internet 不等于失败。本次有多个 RoboCommand 实例，不把默认网关当成待连接的 broker。')
h('窗口 A 连接前检查', 2)
p('以下各页主命令在同一个已加载 ROS 2 的 PowerShell 窗口 A 运行，保留变量。将当前目录设为实际仓库根目录；其他电脑修改这里的路径。')
code(r'''Set-Location 'C:\Users\admin\Desktop\PhD_Tongji\RobotX2026\OCS\robotx-communication'
$OfficialBroker = (Read-Host '输入工作人员分配的 RoboCommand IP').Trim()
if ($OfficialBroker -notmatch '^192\.168\.69\.[2-6]$') {
    throw '地址不在本通知的实例范围内，请先向工作人员核实'
}
$OfficialPort = 1883
Test-NetConnection -ComputerName $OfficialBroker `
  -Port $OfficialPort -InformationLevel Detailed''')
table(['观察项', '预期结果'], [
    ['TcpTestSucceeded', 'True'],
    ['InterfaceAlias', '实际连接官方网线的接口'],
    ['SourceAddress', '官方 DHCP 分配给本电脑的 192.168.69.x 地址'],
], [1.8, 5.0])
p('端口不通时先核对实例、端口、网线、路由与防火墙。若 UAV 内网也使用 192.168.69.0/24，先解决网段冲突。不要通过桥接让飞机直接进入官方网络。不要为排查 MQTT 关闭承担 UAV 通信的网卡。')
p('当前客户端支持匿名明文 MQTT/TCP；若官方给出账号、密码或 TLS 要求，此版本还需适配，不能只改端口继续。')

page('3 确认 ROS 上行与运行环境')
p('在插着官方网线时复查 ROS。沿用已测通的 ROS_DOMAIN_ID、RMW 和 DDS 网卡设置。OCS 直接订阅 ROS 2，不需要 uav_status_mqtt_bridge.py、内部 MQTT broker、ocs_gateway.py 或 USV 状态机。')
code('''ros2 topic type /tongji_mrl/tsky/uav_status
ros2 topic info /tongji_mrl/tsky/uav_status --verbose
ros2 topic echo /tongji_mrl/tsky/uav_status''')
p('预期：类型为 std_msgs/msg/String；data 内 JSON 的 vehicle_id 为 UAV1；真实数据持续更新。订阅端采用 RELIABLE、VOLATILE、depth 10，发布 QoS 必须兼容。观察后按 Ctrl+C 停止 echo，保留 Orin 发布程序。')
p('核对 GNSS lock、经纬度、速度、航向、HAE 高度，以及真实 MANUAL/AUTO/KILLED 和 GROUNDED/AIRBORNE 状态。若含 sent_at_unix_ms 或 timestamp_unix_ms，Orin 与 OCS 时钟需同步；偏差或数据年龄超过约 3 秒会被拒绝或停止转发。')
h('选择同一 ROS 环境中的 Python', 2)
code(r'''if (Test-Path .\.venv-ground\Scripts\python.exe) {
    $GroundPython = (Resolve-Path .\.venv-ground\Scripts\python.exe).Path
} else {
    $GroundPython = (Get-Command python).Source
}
& $GroundPython -c "import sys; print(sys.executable); print(sys.version)"
& $GroundPython -c "import rclpy, std_msgs.msg, paho.mqtt.client, google.protobuf; print('IMPORT_OK')"''')
p('预期：Python 为 3.10 或以上，并输出 IMPORT_OK。rclpy 的二进制版本必须匹配该解释器。不要自动改用仓库旧 .venv；若 rclpy 导入失败，回到已经测通的 ROS 环境。')
h('仅在接入前缺少依赖时执行', 2)
code(r'''& $GroundPython -m pip install -r .\OCS\requirements.txt''')
p('依赖应在有互联网的准备阶段安装好；当前固定 paho-mqtt 2.0.0、protobuf 7.35。该命令不负责安装或修复 ROS 2。安装后重新检查 IMPORT_OK。')
h('留存真实输入样本', 2)
p('需要留存输入证据时，另开已加载相同 ROS 环境的窗口 B，在仓库根目录执行。收集足够样本后 Ctrl+C；它只读取 topic。')
code(r'''New-Item -ItemType Directory -Force .\logs | Out-Null
$RosStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
ros2 topic echo /tongji_mrl/tsky/uav_status |
  Tee-Object -FilePath ".\logs\ros-$RosStamp.txt"''')

page('4 填写真实身份和合法声明配置')
h('窗口 A 输入身份信息', 2)
code(r'''$PilotFirstName = (Read-Host '飞手 first name，Ground 阶段不填 UAPL ID').Trim()
$StickerNumber = (Read-Host '输入真实 CAAS 贴纸号码').Trim() -replace '^AA', ''
if (-not $PilotFirstName -or -not $StickerNumber) {
    throw '飞手名字和贴纸号码必须填写'
}
$UavRegistration = 'TONG-' + $StickerNumber
Write-Host "队伍 TONG  飞手 $PilotFirstName  注册号 $UavRegistration"''')
p('Ground 阶段无 UAPL ID 时，callsign 只填 first name；有 UAPL 后按官方要求填 firstName-UAPL_ID。注册号为 TONG-贴纸号码，删除开头 AA，保留前导零。例：AA001234 对应 TONG-001234；示例不能替代真实号码。上面的命令完成格式拼接，程序本身不会自动补前缀。')
p('uav_pilot_callsign 写入 RunDeclaration，uav_registration 写入每条 Heartbeat。两者与 vehicle_id=UAV1 含义不同。若 Orin JSON 已含非空 uav_registration，必须与此完整字符串一致；未提供或为空时，OCS 使用启动参数补入。')
code(r'''$ConfigPath = '.\OCS\config.uav-ground.local.json'
if (-not (Test-Path $ConfigPath)) {
    Copy-Item .\OCS\config.uav-ground.example.json $ConfigPath
}
notepad $ConfigPath''')
p('保留 UTF-8 无 BOM 编码。启动命令会覆盖 team_id、broker、pilot、registration 和两个 UAV ID；配置文件主要核对下列 run_declaration 字段。')
table(['字段', '启动前必须确定的值'], [
    ['task_tiers', 'task1 至 task4 全部为 "none"'],
    ['uav_geofence_mode', 'auto_course 或 manual，按下文选择'],
    ['uav_geofence', 'auto_course 时为空数组；manual 时填闭合坐标数组，首尾相同'],
    ['uav_geofence_margin_m', 'auto_course 的内缩参数，模板为 2 m'],
    ['uav_geofence_max_altitude_hae_m', '本次批准的声明最高 HAE 高度，正数且不超过适用上限'],
    ['uav_geofence_altitude_limit_hae_m', '现场适用上限，采用同一 HAE 基准'],
], [3.05, 3.75])
p('auto_course 根据本次收到的 RxCourse corners 生成围栏。仅在该候选围栏满足本次 SV 区域要求时使用；如 SV 是独立的小区域，应填已核准的 manual 围栏，每点为 {"latitude": 数值, "longitude": 数值}。手工围栏也必须通过本地 Course/Transit 校验。不要直接沿用模拟 40/50 m，或把相对起飞点高度当作 HAE。三种场景均要求此基线配置合法。')

page('5 启动正常流程并确认声明发布')
p('先核对 TONG、UAV1 的现场登记、飞手、注册号、围栏和高度。当前程序收到合法 RxCourse 后立即自动提交声明，不等待 UAV 数据或人工确认。同一 Team/UAV 仅运行一个发布进程。')
h('窗口 A 启动正常场景', 2)
code(r'''New-Item -ItemType Directory -Force .\logs | Out-Null
$RunStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$CommonArgs = @(
    '--config', $ConfigPath,
    '--official-broker', $OfficialBroker,
    '--official-port', "$OfficialPort",
    '--team-id', 'TONG',
    '--vehicle-id', 'UAV1', '--source-vehicle-id', 'UAV1',
    '--pilot-callsign', $PilotFirstName,
    '--uav-registration', $UavRegistration
)
Start-Transcript -Path ".\logs\normal-$RunStamp-console.txt"
& $GroundPython .\OCS\uav_ground_validation.py @CommonArgs `
  --scenario normal --log ".\logs\normal-$RunStamp.jsonl"''')
p('默认持续运行，不加 --duration；有效观察时长从 MDF 真正开始更新后计算。按下列里程碑检查，短暂 WAIT 状态可能很快跳过。')
table(['日志里程碑', '预期结果与判断'], [
    ['GROUND_SESSION_START', 'source_transport=ros2，正确 topic 和 UAV 身份；vehicle_commands_enabled=false'],
    ['[MQTT] connected; subscribed', 'MQTT 已连接并发起 Course 和队伍 command 订阅；仍需实际收包证明订阅有效'],
    ['[RxCourse]', '收到并通过解码和本地校验；核对 course_id、corners 和 transit 与现场一致'],
    ['DECLARING', '使用当前 Course 构造并校验单 UAV 声明'],
    ['DECLARATION_PUBLISHED', '记录 declaration_seq、course_id、pilot、实际闭合围栏和最高高度'],
], [2.25, 4.55])
p('声明的四个任务 tier 均为 NONE。DECLARATION_PUBLISHED 的 transport_ack 是 MQTT PUBACK only，outcome 为 acceptance_unknown：只证明 broker 确认收到，不能替代官方业务受理或 MDF 验收。声明后由现场人员核对本次创建的 flight。')
h('TONG 的官方 topic', 2)
code('''robocommand/robotx/course
robocommand/robotx/TONG/request
robocommand/robotx/TONG/command
robocommand/robotx/TONG/UAV1/report''', executable=False)

page('6 验证真实心跳和 MDF 显示')
p('有新鲜有效 ROS 数据后，阶段进入 HEARTBEATING，并约每 0.5 秒输出一条 HEARTBEAT_PUBLISHED。report_seq、count 应递增，state 和 flight_phase 应与真实 UAV 一致，current_task 固定为 TASK_NONE。')
p('WAIT_UAV_TELEMETRY 表示尚无有效输入；UAV_TELEMETRY_STALE 表示数据超过约 3 秒。程序会停止发送缓存心跳，待有效数据恢复后继续。来源未带时间戳时，age_s 只能证明 OCS 收包新鲜度，不能证明 GNSS 到 MDF 的端到端延迟。')
h('MDF 1 至 4 的现场验收', 2)
table(['项目', '操作与预期结果'], [
    ['MDF 1', '开启真实 UAV 遥测子系统；官方 RoboCommand 将数据转入 MDF，显示正确 UA 或 Drone ID'],
    ['MDF 2', 'GNSS lock 后，核对 state、flight phase、位置、速度、航向和高度；显示位置距已知地面位置不超过 50 m'],
    ['MDF 3', '确认本次请求建立正确 flight，UA 或 Drone ID、pilot、提交围栏和最高高度全部正确'],
    ['MDF 4', '从 MDF 实际开始更新后连续观察至少 1 分钟，无异常中断或位置停滞；允许最多 5 秒延迟'],
], [1.0, 5.8])
p('OCS 的 HEARTBEAT_PUBLISHED JSONL 不含完整位置、速度和高度。字段对照需使用第 3 页保存的 ROS 样本和官方解码记录或 MDF 画面，并记录观察起止时间。PUBACK、计数增长及进程退出码均不能单独证明 MDF 通过。')
h('需要验证 RunStart 时', 2)
p('由飞手按考官安排使 UAV 进入真实 AUTO 并满足官方其余启动条件。MANUAL 下可以持续发送心跳，没有 RunStart 不等于通信失败。以真实系统条件为准，不假定像公开模拟服务一样自动放行。')
code('''[RunStart] accepted declaration_seq=... run_id=...
RUN_START_RECORDED''', executable=False)
p('预期：收到当前队伍的有效命令，declaration_seq 与本轮声明一致，run_id 非零；程序记录 vehicle_commands_sent=0。run_id 属于 RunStart 和本地会话，官方 RxReport 本身没有该字段。')
p('飞机进入 AUTO 后的待命和保持由飞手及飞控系统保证。本 ground 入口不会把 RunStart、Course 或围栏下发给飞机；MDF 显示了声明围栏，也不代表机载系统已加载该围栏。')

page('7 完成 SYS1 并切换到越界测试')
h('SYS1 合法请求', 2)
p('第 5 页 normal 即用于合法请求。确认提交围栏在适用 SV 空域内，最高高度不超过该空域上限；由官方或 MDF 确认未被边界和高度检查拒绝。是否有 RunStart 取决于真实 AUTO 和其他现场条件，不单凭它判断 SYS1。')
h('每次切换场景前', 2)
p('在窗口 A 按 Ctrl+C 停止上一进程，然后执行 Stop-Transcript。请现场人员确认上一轮已结束或本队测试会话已重置，再开始下一轮。当前程序每次重新启动会重新初始化序号；不要在同一活动 run 中反复重启。保留正式 team_id=TONG，不自行重启官方服务，也不使用 GVSYS 测试队名。')
p('CommonArgs 保存创建时的值。更换 broker、身份或配置路径后，重新执行第 5 页的 $CommonArgs = @(...) 赋值块；只修改原变量不会更新已有参数数组。')
code('''Stop-Transcript''')
h('SYS2 声明围栏越界', 2)
p('前提：现场人员确认本模式产生的围栏确实越出本次适用 SV 边界。程序先验证合法基线，然后把整个闭合声明围栏平移到收到的 Course 和 Transit 最北界之外至少 20 m；它不直接读取另一个独立 SV 多边形。若此变换不能满足当前 SV 的测试要求，先调整测试方案，不把它当作自动覆盖 SYS2。')
code(r'''$RunStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Start-Transcript -Path ".\logs\sys2-$RunStamp-console.txt"
& $GroundPython .\OCS\uav_ground_validation.py @CommonArgs `
  --scenario outside-course --outside-offset-m 20 `
  --log ".\logs\sys2-$RunStamp.jsonl"''')
p('预期：先收到当前 RxCourse，再看到 DECLARATION_PUBLISHED，其中实际围栏已外移。基线高度、pilot、registration 和实际 UAV 心跳位置保持原值；不移动飞机，不伪造 GPS。真实心跳在输入有效时继续发送。')
p('通过依据：官方或 MDF 明确 denied 或 held，且原因是越出本次适用 SV 边界。保存带本队、飞机身份和本轮时间的画面或官方记录。不能要求真实服务使用模拟脚本完全相同的 refused 文本。')
p('没有 RunStart 不能单独证明拒绝；负例收到匹配 RunStart 会输出 SCENARIO_FAILED 并退出。负例提交后断线或 Course 变化也会退出，先核对官方状态再重测。偏移参数范围为 2 至 100000 m。')
p('取证结束后 Ctrl+C，再执行 Stop-Transcript，由现场人员确认切换到下一测试轮。')

page('8 执行超高测试并结束本轮')
h('SYS3 声明最高高度超限', 2)
p('保持配置文件中的围栏和基线高度合法。与考官确定一个明确高于现场适用上限的声明高度，单位必须为 m HAE。不能默认 60 m 一定超限。当前参数还要求值在 (50,100000] 内，且 protobuf 编码后仍大于 50；这是入口限制，不是现场空域上限。如果考官指定的超限测试值仍不超过 50，需先适配程序才能使用该值。')
code(r'''$TestMaxHae = Read-Host '输入经现场确认的超限声明高度，单位 m HAE'
$RunStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Start-Transcript -Path ".\logs\sys3-$RunStamp-console.txt"
& $GroundPython .\OCS\uav_ground_validation.py @CommonArgs `
  --scenario over-height --test-max-altitude-hae $TestMaxHae `
  --log ".\logs\sys3-$RunStamp.jsonl"''')
p('预期：声明仅最高高度改为测试值；围栏、身份和四个 NONE 不变。Heartbeat 高度仍来自真实 ROS 数据，无需升高飞机。')
p('通过依据：官方或 MDF 明确 denied 或 held，原因为超过适用高度限制。保存声明高度、实际限制和原因。匹配 RunStart、断线或 Course 变化会使本入口判为失败并退出。')
h('结束与证据归档', 2)
p('取证后 Ctrl+C，再保存记录。后续新轮次保留窗口 A 变量；若关闭窗口，则从第 2 页重新初始化。')
code(r'''Stop-Transcript
$EvidenceStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item $ConfigPath ".\logs\config-$EvidenceStamp.json"
git rev-parse HEAD | Set-Content ".\logs\code-$EvidenceStamp.txt"''')
p('配置副本不一定含 CLI 覆盖值；另记实际 broker、TONG、UAV1、飞手和完整注册号，与当轮声明及 MDF 对照。共享前移除无关个人信息。')
table(['每轮保存', '内容'], [
    ['OCS 日志', '对应场景的 JSONL、console transcript；其中包含实际声明围栏、高度、declaration_seq 和状态'],
    ['真实输入与时间', 'ROS 样本、GNSS lock、OCS 与 UAV 时间同步情况、MDF 观察起止时间'],
    ['官方侧证据', '正常 flight 的身份与遥测画面；SYS2/SYS3 的 denied 或 held 原因；考官确认结果'],
    ['运行条件', '代码提交、实际使用配置和 CLI 覆盖值、ROS/Python 版本、网络与实例地址'],
], [1.55, 5.25])
p('退出码 0 不等于验收通过，正式结果由考官填写。本手册覆盖通信、MDF 和边界高度检查；其他 Ground Screening 项目及受控飞行验证按完整官方表执行。')

page('9 现场故障定位与结果记录')
table(['现象', '优先检查'], [
    ['没有 DHCP 地址或为 169.254', '官方网口、IPv4 自动获取、网线和现场 DHCP；不自行配置静态比赛地址'],
    ['TCP 1883 不通', '指定的 .2 至 .6 实例、官方服务、InterfaceAlias、SourceAddress、路由和防火墙'],
    ['WAIT_ROBOCOMMAND', 'MQTT 连接情况；端口通不等于 MQTT 登录或协议通过，检查是否有认证/TLS要求'],
    ['WAIT_COURSE', '当前 RxCourse 是否发布、订阅权限及解码/校验错误；不要用旧场地坐标替代'],
    ['WAIT_UAV_TELEMETRY 或 STALE', '插官方网线后 DDS 是否仍通、QoS、真实发布进程、3 秒新鲜度及源时间戳'],
    ['UAV_REJECTED', '按 reason 检查 JSON、来源 UAV1、字段范围、模拟标记和 registration 一致性'],
    ['声明前本地围栏或高度报错', '恢复合法基线，核对 Course/Transit、闭合坐标与 HAE 上限；负例用场景参数'],
    ['本地持续发送但 MDF 无更新', '请官方查 TONG/UAV1 身份映射、声明 hold/reject 原因、遥测转发和 flight'],
    ['PUBACK 超时或发布报错', '程序退出后先确认官方是否已收到声明，再决定重测，避免不确定的重复提交'],
], [2.15, 4.65])
h('本次现场结果', 2)
p('日期与地点 ____________________    操作员与考官 ____________________\nMDF 1 至 4 ________    SYS1 ________    SYS2 ________    SYS3 ________\nRunStart 如安排 ________    各项填写 通过 / 失败 / 未执行\n限制或待办 __________________________________________________')
h('版本与依据', 2)
p('实现基线 0aada73，138 项 OCS 回归通过。本地 6 个 proto 和 6 个运行 pb2.py 与 2026-11-07 核对的官方 main 8fc09f2 一致；两个身份字段序列化检查通过。现场 DDS 和 MDF 验收以本轮记录为准。')
p('依据：两张官方现场通知；Team Handbook 20261023 第 3.4 节；Technical assessment Ground validation test list 第 4 至 5 页。')
link('官方 RobotX 2026 协议版本', 'https://github.com/robonation/robocommand/tree/' + SHA + '/RobotX_2026')

doc.core_properties.title = 'RobotX UAV 官方现场地面验证操作手册'
doc.core_properties.subject = 'TONG Windows ROS 2 直连官方 RoboCommand 的 Ground Validation 操作流程'
doc.core_properties.author = 'Tongji RobotX'
doc.core_properties.keywords = 'TONG RobotX UAV Ground Validation ROS2 RoboCommand MDF'
OUT.mkdir(exist_ok=True)
doc.save(DOC)
print(DOC)
