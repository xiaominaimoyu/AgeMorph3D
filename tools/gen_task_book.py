# -*- coding: utf-8 -*-
"""生成《岁月镜 AgeMorph3D 毕业设计任务书》docx。

结构参照：西华大学《1-任务书模板.docx》+ YOLO 任务书实例，
研究内容以《AgeMorph3D_毕设可行性分析.md》为核心。
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = r"D:\project file\AgeMorph3D\docs\【任务书】岁月镜AgeMorph3D-基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统.docx"

BODY_E = '宋体'
HEAD_E = '黑体'
ASCII_F = 'Times New Roman'


def set_font(run, east=BODY_E, size=12, bold=False, ascii_f=ASCII_F):
    run.font.name = ascii_f
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn('w:eastAsia'), east)
    rFonts.set(qn('w:ascii'), ascii_f)
    rFonts.set(qn('w:hAnsi'), ascii_f)


def para(container, text, east=BODY_E, size=12, bold=False, align=None,
         indent=True, before=0, after=0, line=20, style=None):
    p = container.add_paragraph(style=style)
    pf = p.paragraph_format
    if align is not None:
        pf.alignment = align
    if indent:
        pf.first_line_indent = Pt(size * 2)
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(line)
    r = p.add_run(text)
    set_font(r, east=east, size=size, bold=bold)
    return p


def h1(container, text):
    return para(container, text, east=HEAD_E, size=14, bold=True,
                indent=False, before=10, after=4, line=24)


def h2(container, text):
    return para(container, text, east=HEAD_E, size=12, bold=True,
                indent=False, before=6, after=2, line=20)


def body(container, text):
    return para(container, text, size=12, line=22)


def shade(cell, fill='D9D9D9'):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    tcPr.append(shd)


def cell_text(cell, text, size=10.5, bold=False, align=None, east=BODY_E):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.text = ''
    pf = p.paragraph_format
    pf.space_before = Pt(2)
    pf.space_after = Pt(2)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(15)
    if align is not None:
        pf.alignment = align
    parts = text.split('\n')
    for i, part in enumerate(parts):
        if i > 0:
            p = cell.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = Pt(0)
            pf.space_after = Pt(2)
            pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            pf.line_spacing = Pt(15)
            if align is not None:
                pf.alignment = align
        r = p.add_run(part)
        set_font(r, east=east, size=size, bold=bold)


doc = Document()

# 页面设置 A4
sec = doc.sections[0]
sec.page_width = Cm(21.0)
sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.54)
sec.bottom_margin = Cm(2.54)
sec.left_margin = Cm(3.17)
sec.right_margin = Cm(3.17)

# ============ 标题区 ============
para(doc, '毕  业  设  计  任  务  书', size=22, bold=True,
     align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, before=6, after=6, line=34)
para(doc, '（理工类）', size=15,
     align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=10, line=26)

# ============ 信息表 ============
info = [
    ('题　　目', '岁月镜（AgeMorph3D）——基于YOLO与三维形变模型的跨年龄三维人脸重建及可视化系统'),
    ('学生姓名', '＿＿＿＿＿＿＿＿（组长）　　　　＿＿＿＿＿＿＿＿（组员）'),
    ('学　　号', '＿＿＿＿＿＿＿＿＿＿＿＿　　　　＿＿＿＿＿＿＿＿＿＿＿＿'),
    ('专　　业', '计算机科学与技术'),
    ('年　　级', '2023级'),
    ('学　　院', '计算机与软件工程学院'),
    ('指导教师', '＿＿＿＿＿＿＿＿'),
]
t = doc.add_table(rows=len(info), cols=2)
t.style = 'Table Grid'
t.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, (k, v) in enumerate(info):
    c0, c1 = t.rows[i].cells
    c0.width = Cm(3.2)
    c1.width = Cm(11.4)
    cell_text(c0, k, size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, east=HEAD_E)
    cell_text(c1, v, size=12)

para(doc, '教务处制', size=14, align=WD_ALIGN_PARAGRAPH.CENTER,
     indent=False, before=12, after=2, line=24)
para(doc, '2026年12月', size=14, align=WD_ALIGN_PARAGRAPH.CENTER,
     indent=False, after=8, line=24)

# ============ 正文 ============
h1(doc, '毕业设计任务与要求：')

# ---------- 一、研究背景与意义 ----------
h1(doc, '一、课题研究背景与意义')

h2(doc, '（一）研究背景')
body(doc, '三维人脸重建与年龄可视化是计算机视觉、计算机图形学与深度学习交叉领域的前沿方向。传统三维人脸采集依赖三维扫描仪、结构光或多目相机等精密设备，成本高、周期长，难以普及；基于三维形变模型（3D Morphable Model，3DMM）的回归方法只需一张普通照片即可恢复人脸的三维形状、表情与纹理，大幅降低了三维内容的创作门槛，已成为数字人、虚拟试戴、影视特效、游戏捏脸、医疗美容预演等应用的核心技术。')
body(doc, '与此同时，“看到自己未来的样子”存在广泛而真实的需求：影视制作需要角色老化/减龄预演，寻亲与社会救助需要依据童年照片推断失踪儿童多年后的样貌，跨年龄人脸识别需要缓解年龄变化带来的特征衰减，个人用户则希望通过形象预览辅助美容、美发等决策。二维人脸年龄变换（基于GAN与扩散模型）已较为成熟，但在三维空间中的年龄变换研究2023年以来才陆续出现，公开可用的实现极少。')
body(doc, '另一方面，WebGL与three.js等Web三维技术的普及，使三维应用从“下载安装”走向“打开浏览器即用”。将人脸检测、三维重建、年龄变换与Web三维可视化集成为完整系统，让用户在摄像头前实时看到自己不同年龄的三维头像，具有明确的技术可行性与应用价值。但截至目前，开源社区尚未见“摄像头—三维头模—跨年龄”完整链路的实现，本课题即面向这一空白。')

h2(doc, '（二）研究意义')
body(doc, '1. 学术意义：本课题将YOLO人脸检测、3DMM单图重建、二维年龄变换模型与Web三维可视化集成为完整系统，覆盖“检测—重建—变换—渲染”全链路。核心创新点在于用数据统计方法估计形变模型空间中的“年龄方向”——利用带年龄标签的大规模人脸数据集批量重建获得形状参数，再按年龄回归得到统计意义上的年龄变化方向，将三维老化解耦为形状形变与纹理老化两部分。该思路与ICME 2024的3D-STD方法一致，但由本团队自行实现，可加深对参数化三维人脸模型数学本质的理解。')
body(doc, '2. 应用价值：系统完全在本地处理人脸数据，不依赖云端，规避隐私风险；浏览器直接运行、无需安装，可应用于个人形象预览、影视角色预演、教学演示等场景；“仅传参数、不传网格”的轻量架构可复用于其他3DMM应用。')
body(doc, '3. 工程意义：课题涉及深度学习推理优化（ONNX）、前后端分离与实时通信（WebSocket）、三维资产导出（glTF）等工程实践，能够综合训练本科阶段的工程能力。')

h2(doc, '（三）国内外研究现状')
body(doc, '1. 三维形变模型：Blanz与Vetter于1999年提出3DMM（SIGGRAPH），奠定参数化人脸建模基础；BFM（2009）附带年龄、性别等属性方向；FLAME（TOG 2017）扩展为包含颅形、颈部与眼球的全头模型；LSFM（IJCV 2018，9663人）、LYHM（IJCV 2020，全头）等大规模模型按年龄组建模；Google于2026年发布的GNM Head（Apache-2.0协议）进一步免除了模型许可障碍。')
body(doc, '2. 单图三维人脸重建：从PRNet（ECCV 2018）到3DDFA_V2（ECCV 2020，轻量、CPU实时）、DECA（SIGGRAPH 2021）、MICA（ECCV 2022，度量精度高）、HRN（CVPR 2023）等，预训练模型已可直接集成。')
body(doc, '3. 人脸检测：YOLO系列持续演进，YOLO5Face（ECCV Workshops 2022）验证了YOLO架构在人脸检测（含5个关键点）上的有效性。')
body(doc, '4. 人脸年龄变换：二维方向从CAAE（CVPR 2017）、IPCGAN（CVPR 2018）、LATS（ECCV 2020，含头型变化）发展到SAM（SIGGRAPH 2021，连续年龄控制）及扩散模型方案（FADING，BMVC 2023；Cradle2Cane，NeurIPS 2025）；三维方向以3D-STD（ICME 2024，形状—纹理解耦）与DiffAge3D（2024）为代表，但均未发布可用代码。')
body(doc, '5. Web三维可视化：three.js的morph target机制与官方示例（webgl_morphtargets_webcam）为本系统的前端实现提供了直接参考。')
body(doc, '综上，单项技术均较成熟，但完整链路的开源系统缺失，本课题的集成工作具有实际创新空间。')

# ---------- 二、研究内容与技术路线 ----------
h1(doc, '二、研究内容与技术路线')

h2(doc, '（一）研究目标与内容')
body(doc, '总体目标：设计并实现“岁月镜（AgeMorph3D）”系统——用户面对摄像头或上传一张照片，系统自动检测人脸并重建为三维头模；用户拖动年龄滑块（20—70岁），即可在浏览器中实时预览自己在不同年龄的三维形象，并可导出三维模型与效果图。')
body(doc, '围绕总体目标，课题由三个模块构成：')
body(doc, '模块一：人脸检测与对齐。以YOLO26n-face人脸检测器替换3DDFA_V2自带的FaceBoxes，输出人脸框与5个关键点，完成裁剪与对齐；在WIDER FACE数据集上微调，报告mAP与FPS，作为论文“模型训练与实验”章节的内容。')
body(doc, '模块二：单图三维人脸重建。保底方案采用3DDFA_V2＋BFM（自带处理好的模型文件与摄像头演示，CPU可实时运行）；主线方案采用MICA＋FLAME获得全头模型（脸型估计更准确）。输出形状参数β、表情参数ψ、头部姿态与UV纹理贴图。')
body(doc, '模块三：跨年龄变换与三维可视化。（1）年龄方向估计（核心创新）：保底做法是将BFM 2009自带的年龄属性方向换算为逐顶点位移，作为three.js的morph target；主线做法是用带年龄标签的UTKFace、FFHQ-Aging数据集批量重建，获得大量FLAME形状参数后按年龄回归，得到FLAME空间的年龄方向，按β′＝β＋w(age)·Δβ_age进行形状老化。（2）纹理老化：用SAM生成目标年龄的人脸照片，经UV展开贴回三维模型，表现皱纹、肤色等纹理变化。（3）可视化：将年龄方向导出为glTF的morph target，前端用three.js渲染，通过滑块控制权重。')

h2(doc, '（二）技术路线')
body(doc, '系统流水线：摄像头/照片 → YOLO26n-face检测 → 裁剪对齐 → 3DMM回归（3DDFA_V2/MICA）→ 形状β、表情ψ、姿态、UV纹理 → 年龄变换β′＝β＋w(age)·Δβ_age，纹理经SAM生成 → 导出glTF（年龄方向为morph target）→ three.js渲染＋年龄滑块。')
body(doc, '系统架构采用前后端分离：后端（Python/FastAPI）负责任务密集的人脸检测、三维重建与年龄变换，模型以ONNX导出以保证推理速度；前端（three.js）一次性加载模板网格与形状基，通过WebSocket与后端交互，每帧仅传输数十个浮点参数而不传输网格数据（FLAME仅5023个顶点，适合在浏览器端完成形变计算）；实时流程（检测、姿态驱动）逐帧进行，年龄变换按“拍照—生成—查看”的离线流程执行。')
body(doc, '实施策略采用“保底＋主线”双路径：保底版（约6—8周，确保按期毕业）为YOLO＋3DDFA_V2＋BFM年龄方向＋three.js；主线版为MICA＋FLAME＋自估计年龄方向＋SAM纹理；可选加分版将LAM、FaceLift、混元Hunyuan3D-2.1等单图三维生成方法置于对比展示部分（非参数化模型，无法实现年龄滑块）。')

h2(doc, '（三）开发与运行环境')
body(doc, '开发工具：Python、PyTorch、OpenCV、ONNX Runtime、FastAPI、JavaScript/three.js；开发环境为PyCharm/VS Code＋WSL2 Ubuntu＋Git。')
body(doc, '硬件平台：RTX 5060 Laptop（8GB显存）、31GB内存、Windows 11＋WSL2 Ubuntu。需注意：50系显卡要求CUDA 12.8与PyTorch 2.7以上版本；扩散类模型在8GB显存上采用半精度推理。')
body(doc, '运行环境：PC，Windows/Linux，Chrome/Edge等支持WebGL 2.0的浏览器。')

# ---------- 三、二人小组分工协作方式 ----------
h1(doc, '三、二人小组分工协作方式')

h2(doc, '（一）团队组成与分工')
body(doc, '本课题由2人组成开发团队，按照“算法—系统”双线分工，职责清晰、接口明确：')
body(doc, '组长（学生A）：负责三维重建与年龄变换算法模块。包括YOLO人脸检测集成与WIDER FACE微调、3DMM回归（3DDFA_V2/MICA）集成与优化、BFM/FLAME年龄方向估计、SAM纹理老化、算法实验与评价指标测试，并负责论文算法章节的撰写。')
body(doc, '组员（学生B）：负责可视化系统与工程实现模块。包括毕设课题的经济效益与社会贡献分析、法律法规/健康/安全/环境关联分析、技术选型对比分析；three.js三维渲染、morph target年龄滑块与纹理映射、前端UI与交互、FastAPI＋WebSocket后端服务、glTF导出接口、系统集成测试与演示视频录制，并负责论文系统章节的撰写。')
body(doc, '二人共同承担：文献调研、开题报告、系统总体设计、前后端接口约定、论文绪论与总结章节、数据合规文档。')

h2(doc, '（二）协作机制')
body(doc, '1. 代码管理：使用Git仓库（GitHub/Gitee）托管全部代码与文档，采用分支开发与约定式提交，关键节点打标签；')
body(doc, '2. 接口先行：开发前先共同确定前后端接口文档（JSON参数格式），后端提供Mock数据，双方并行开发、后期联调；')
body(doc, '3. 进度同步：每周至少一次例会同步进度与问题，使用在线文档维护任务看板，里程碑与学校时间节点对齐；')
body(doc, '4. 质量保障：互相进行代码审查，模块完成后先经单元测试再集成；模型文件、数据集等大文件不入库，通过说明文档记录获取方式；')
body(doc, '5. 问题升级：技术阻塞超过一周未解决时，共同向指导教师汇报，及时调整方案（如从主线版切换至保底版）。')

# ---------- 四、预期成果形式 ----------
h1(doc, '四、预期成果形式')
body(doc, '1. 软件系统：“岁月镜”Web应用一套，支持摄像头实时检测、三维头模重建、年龄滑块（20—70岁）跨年龄预览与glTF导出，在Chrome/Edge浏览器中运行；')
body(doc, '2. 毕业设计说明书：每人一篇，含绪论、相关技术、系统设计、算法实现、实验评价、总结等章节，图表均为自行绘制；')
body(doc, '3. 实验数据与报告：人脸检测mAP/FPS、重建关键点误差（NME）、年龄变换评价（MiVOLO估计年龄差、ArcFace身份相似度、FG-NET直观对比）、系统端到端延迟与渲染帧率、10—20人主观打分；')
body(doc, '4. 演示视频：3—5分钟系统功能演示视频；')
body(doc, '5. 过程文档：开题报告、中期报告、外文资料翻译（每人一篇，与本人分工相关）、数据合规文档（知情同意书、本地处理声明）；')
body(doc, '6. 源代码：完整可运行的源码仓库（含README、环境配置说明）。')

# ---------- 五、设计任务 ----------
h1(doc, '五、设计任务')

h2(doc, '（一）开发团队与工作量')
body(doc, '开发团队：2人。工作量：代码量≥1500行/人（最低要求），项目总代码量≥4500行。')

h2(doc, '（二）系统功能性')
body(doc, '本系统的功能包括：（1）通过摄像头实时检测并跟踪人脸，输出人脸框与关键点；（2）将单张照片或视频帧重建为三维头模，输出形状、表情、姿态与UV纹理；（3）跨年龄三维形变：年龄滑块在20—70岁范围内连续调节，实时驱动morph target，预览不同年龄的三维形象；（4）纹理老化：生成目标年龄的人脸纹理并贴回三维模型；（5）结果导出：导出glTF三维模型与效果图；（6）系统管理：模型加载、参数配置与推理日志。')

h2(doc, '（三）创新性')
body(doc, '本课题的创新性体现在：（1）方法创新：提出用数据统计方法估计三维形变模型空间中的“年龄方向”——用带年龄标签的大规模人脸数据集批量重建获得形状参数，按年龄回归得到年龄变化方向，将三维老化解耦为形状形变（β′＝β＋w(age)·Δβ_age）与纹理老化（SAM生成）两部分并重新组合，该思路与ICME 2024的3D-STD一致，但由本团队自行实现，且直接服务于可交互的Web系统；（2）集成创新：据公开调研，开源社区尚无“YOLO检测—3DMM重建—年龄变换—three.js可视化”完整链路的实现，本课题将该链路集成为可演示的完整系统；（3）工程创新：采用“仅传参数、不传网格”的轻量前后端架构，实时流程与离线流程分离，兼顾交互体验与计算成本。')

h2(doc, '（四）实用性')
body(doc, '系统在本地完成全部人脸数据处理，不依赖云端服务，规避人脸敏感信息泄露风险，符合《个人信息保护法》与《人脸识别技术应用安全管理办法》的合规要求；浏览器直接运行、无需安装，普通摄像头即可采集，使用门槛低；可应用于个人形象预览、影视角色老化/减龄预演、跨年龄人脸识别教学演示等场景，具有较强的实用性与推广价值。')

# ---------- 六、主要设计内容与要求 ----------
h1(doc, '六、主要设计内容与要求')

h2(doc, '（一）团队任务')
body(doc, '1. 系统设计：系统总体架构、前后端接口与数据流设计；')
body(doc, '2. 算法实现：人脸检测（YOLO）、三维重建（3DMM）、年龄变换（年龄方向＋SAM纹理）三类核心算法与模型实现；')
body(doc, '3. 数据获取：整理WIDER FACE、AFLW2000-3D、UTKFace、FFHQ-Aging等数据集，按学校规定与知情同意原则采集合成测试用照片；')
body(doc, '4. 编程实现：Python实现算法与后端服务，JavaScript/three.js实现前端可视化；')
body(doc, '5. UI设计：友好方便的用户界面，包含摄像头调用、拍照、年龄滑块、模型导出等；')
body(doc, '6. 系统测试：设计测试用例，完成功能测试、性能测试（延迟/帧率）与兼容性测试；')
body(doc, '7. 开发文档：需求调研、概要设计、详细设计、测试用例等。')

h2(doc, '（二）个人任务')
body(doc, '组长（学生A）：')
body(doc, '1. YOLO26n-face人脸检测模块：集成与WIDER FACE微调，完成mAP/FPS评测；')
body(doc, '2. 三维重建模块：3DDFA_V2/MICA集成与推理优化，完成AFLW2000-3D关键点误差（NME）评测；')
body(doc, '3. 年龄方向估计：BFM年龄方向换算为顶点位移；基于UTKFace/FFHQ-Aging回归FLAME空间年龄方向；')
body(doc, '4. SAM纹理老化模块：目标年龄纹理生成与UV展开贴回；')
body(doc, '5. 算法实验与评价：MiVOLO年龄差、ArcFace身份相似度、FG-NET对比实验；')
body(doc, '6. 论文算法章节（三维重建、年龄变换、实验评价）撰写。')
body(doc, '组员（学生B）：')
body(doc, '1. 毕设课题的经济效益与社会贡献分析，与法律、法规、健康、安全、环境等因素的关联分析，技术选型对比分析；')
body(doc, '2. three.js三维可视化：模板网格与形状基加载、morph target年龄滑块、纹理映射与光照；')
body(doc, '3. 前端UI与交互：摄像头调用、拍照流程、年龄调节、导出功能；')
body(doc, '4. 后端服务：FastAPI＋WebSocket、ONNX推理加速、glTF导出接口；')
body(doc, '5. 系统集成测试：端到端延迟、渲染帧率、浏览器兼容性测试与优化；')
body(doc, '6. 论文系统章节（需求分析、系统设计、前端实现）撰写与演示视频录制。')

h2(doc, '（三）本设计中的“复杂工程问题”')
body(doc, '按照《工程教育专业认证标准》，复杂工程问题必须具备下述特征（1）；同时，具备下述特征（2）—（7）的部分或全部。本设计具备其中的特征（1）（2）（3）（4）：')
body(doc, '具备特征（1）：为实现三维重建，需深入理解三维形变模型的形状基、表情基的数学构造与回归网络的原理；为实现年龄变换，需理解“年龄方向”的统计假设与线性组合的合理性；上述内容均需经过分析才能正确运用。')
body(doc, '具备特征（2）：本系统涉及人脸检测、三维重建、年龄变换、Web三维渲染、前后端实时通信等多方面技术，需要综合运用并协调彼此之间的约束。')
body(doc, '具备特征（3）：本设计将“人的老化”抽象为形变模型参数空间中的方向向量（Δβ_age）与纹理空间的变换，通过建立该抽象模型才能实现连续、可交互的年龄调节。')
body(doc, '具备特征（4）：三维人脸老化目前没有成熟的现成代码可直接使用，需要在理解原理的基础上自行实现与调优，无法仅依靠常用方法完全解决。')

h2(doc, '（四）设计原则')
body(doc, '1. 独立开发：某些技术或算法可借鉴他人成果，但必须是在理解基础上的借鉴和改进，必须弄懂算法原理、技术手段。否则，视作抄袭，毕业设计成绩不合格。')
body(doc, '2. 方案修改：与导师商议并取得导师同意后可适度修改，不得擅自删减。')
body(doc, '3. 开发过程：遵循软件工程相关规定、阶段、步骤，熟悉工程化开发过程。')

h2(doc, '（五）说明书撰写')
body(doc, '态度严谨，撰写认真，用词简洁准确，无语法、用词、术语、标点符号等错误。')
body(doc, '描述方式恰当，充分阐述设计理念、方案、算法、技术原理等，禁贴源代码代替。')
body(doc, '结构完整、层次清楚、图表美观、符合规定；图表必须绘制，禁止贴图。')
body(doc, '严禁：用而不引、引而不用、伪造数据、抄袭剽窃、买卖论文等学术不端行为。')

# ---------- 七、详细进度安排 ----------
h1(doc, '七、详细进度安排')

sched = [
    ('第一阶段\n调研与开题\n（第1—11周）', '2026.11.16\n—2027.01.31',
     '①文献调研：三维形变模型、单目三维人脸重建、人脸年龄变换、Web三维可视化；②确定技术路线，完成可行性分析，撰写开题报告；③提交FLAME官网注册与BFM 2009下载申请；④搭建WSL2＋PyTorch 2.7＋CUDA 12.8环境，跑通3DDFA_V2摄像头演示；⑤完成系统总体架构设计与前后端接口约定。',
     '二人共同\n（A主导算法预研，B主导可视化预研）'),
    ('第二阶段\n开题与检测基础\n（第12—16周）', '2027.02.01\n—2027.03.07',
     '①提交开题报告并参加开题答辩（2027.02.20—03.01）；②集成YOLO26n-face，在WIDER FACE上微调并评测mAP/FPS；③跑通3DDFA_V2/MICA重建，在AFLW2000-3D上测试NME；④three.js端复现官方morph target示例，完成模板网格与形状基加载。',
     'A：检测与重建\nB：三维渲染'),
    ('第三阶段\n年龄变换与可视化\n（第17—22周）', '2027.03.08\n—2027.04.18',
     '①BFM年龄方向换算为逐顶点位移并导出morph target，实现年龄滑块原型（20—70岁）；②基于UTKFace/FFHQ-Aging批量重建，回归估计FLAME空间年龄方向；③接入SAM生成目标年龄纹理并UV展开贴回；④完成中期报告（2027.04.15—04.20）。',
     'A：年龄方向与纹理\nB：滑块与渲染'),
    ('第四阶段\n系统集成与测试\n（第23—26周）', '2027.04.19\n—2027.05.16',
     '①FastAPI＋WebSocket前后端联调（仅传参数，不传网格）；②glTF导出与浏览器端morph target实时计算；③系统集成测试：端到端延迟、渲染帧率、浏览器兼容性；④实验评价：MiVOLO年龄差、ArcFace身份相似度、FG-NET对比、10—20人主观打分；⑤整理数据合规文档（知情同意书、本地处理声明）。',
     '二人共同'),
    ('第五阶段\n论文与答辩\n（第27—30周）', '2027.05.17\n—2027.06.10',
     '①撰写毕业设计说明书（各自负责本人模块章节，共同撰写绪论与总结）；②完成外文资料翻译；③录制系统演示视频；④查重与修改；⑤指导教师评阅（2027.05.20—06.02）；⑥参加答辩。',
     '二人共同'),
]
st = doc.add_table(rows=1 + len(sched), cols=4)
st.style = 'Table Grid'
st.alignment = WD_TABLE_ALIGNMENT.CENTER
widths = [Cm(3.4), Cm(2.9), Cm(6.6), Cm(2.6)]
hdr = ['阶段', '起讫时间', '主要工作内容', '负责人']
for j, htxt in enumerate(hdr):
    c = st.rows[0].cells[j]
    c.width = widths[j]
    cell_text(c, htxt, size=10.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, east=HEAD_E)
    shade(c)
for i, row in enumerate(sched):
    for j, v in enumerate(row):
        c = st.rows[i + 1].cells[j]
        c.width = widths[j]
        align = WD_ALIGN_PARAGRAPH.CENTER if j in (0, 1, 3) else None
        cell_text(c, v, size=10, align=align,
                  bold=(j == 0), east=(HEAD_E if j == 0 else BODY_E))

para(doc, '风险应对：若主线方案（MICA＋FLAME全头模型）因模型许可或环境问题受阻，及时切换至保底方案（3DDFA_V2＋BFM），确保系统按期完成；儿童头型不在模型表达范围内，主体适用范围限定为20—70岁，儿童相关内容列入论文“局限与展望”。',
     size=10.5, before=6, line=18)

# ---------- 八、参考文献 ----------
h1(doc, '八、推荐主要参考文献和资料')
refs = [
    'Blanz V., Vetter T. A morphable model for the synthesis of 3D faces[C]//Proceedings of SIGGRAPH 1999. Los Angeles: ACM, 1999.',
    'Li T., Bolkart T., Black M J, et al. Learning a model of facial shape and expression from 4D scans[J]. ACM Transactions on Graphics, 2017, 36(6).',
    'Paysan P., Knothe R., Amberg B., et al. A 3D face model for pose and illumination invariant face recognition[C]//Proceedings of AVSS 2009. Genoa: IEEE, 2009.',
    'Egger B., Smith W A P, Tewari A., et al. 3D morphable face models—past, present and future[J]. ACM Transactions on Graphics, 2020, 39(6).',
    'Guo J., et al. Towards fast, accurate and stable 3D dense face alignment[C]//Proceedings of ECCV 2020. Glasgow: Springer, 2020.',
    'Zielonka M., et al. Towards metrical reconstruction of human faces[C]//Proceedings of ECCV 2022. Tel Aviv: Springer, 2022.',
    'Qi D., et al. YOLO5Face: why reinventing a face detector[C]//Proceedings of ECCV Workshops 2022. Tel Aviv: Springer, 2022.',
    'Alaluf Y., Patashnik O., et al. Only a matter of style: age transformation using a style-based regression model[J]. ACM Transactions on Graphics, 2021, 40(4).',
    'Teng Y., et al. Exploring 3D-aware lifespan face aging via disentangled shape-texture representations[C]//Proceedings of ICME 2024. IEEE, 2024.',
    'Kuprashevich M., Krasheninnikov D. MiVOLO: multi-input transformer for age and gender estimation[C]//Proceedings of ICMV 2023. 2023.',
    '刘菲, 张堃博, 杨青, 等. 三维人脸成像及重建技术综述[J]. 中国图象图形学报, 2024, 29(9): 2441-2470.',
    '张珂, 于婷婷, 石超君, 等. 融合通道位置注意力机制和并行空洞卷积的人脸年龄合成[J]. 中国图象图形学报, 2023, 28(12): 3870-3883.',
]
for i, ref in enumerate(refs, 1):
    para(doc, '[%d] %s' % (i, ref), size=10.5, indent=False, line=18, after=2)

doc.save(OUT)
print('saved:', OUT)
