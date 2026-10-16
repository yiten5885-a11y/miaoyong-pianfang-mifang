# 妙用偏方秘方速查

![封面](cover.png)

一个面向 Codex / WorkBuddy 的开源 Skill：把民间验方书《妙用偏方秘方》（易磊 主编，406 页扫描版）整理成可检索的参考库，支持**按症状查方 → 按原书用法整理步骤 → 生成采购清单 → 给出绿/黄/红安全边界**，并在急症、重症、孕期等情况下强制拦截为就医优先。

内容属于资料参考与辅助信息，**不构成诊断、处方、疗效承诺或用药指导**。

## 获取方式

| 渠道 | 地址 |
| --- | --- |
| SkillHub 技能市场 | https://skillhub.cn/skills/miaoyong-pianfang-mifang |
| GitHub 仓库 | https://github.com/yiten5885-a11y/miaoyong-pianfang-mifang |

```bash
# 方式一：SkillHub CLI
curl -fsSL https://skillhub.cn/install/install.sh | bash -s -- --cli-only
skillhub install miaoyong-pianfang-mifang

# 方式二：直接放进本地技能目录
git clone https://github.com/yiten5885-a11y/miaoyong-pianfang-mifang \
  ~/.workbuddy-ai/skills/miaoyong-pianfang-mifang
```


## 这个仓库公开了什么

- 可运行的 Skill 指令（`SKILL.md`）、检索/编排/安全代码（`scripts/`）与规则文档（`references/`）。
- 2395 条结构化方剂记录：方名、原料、制用法、原书所述效用、章节与病症归属、页码与原始行。
- 8 章 230 条的原书目录（`assets/toc.json`）。
- 高毒 / 需炮制 / 需注意药材清单，附在本数据集中的实际出现次数。
- 26 项结构自检（`tests/`）。

## 这个仓库不公开什么

- 原始 PDF 文件，以及任何整页扫描图像。
- OCR 中间产物（`data/`，含行级全文转录）。
- 任何超出原书内容的补写、替代药材、替代剂量或疗效承诺。

## 给用户的体验

直接说出困扰即可：

```text
老咳嗽，痰多，没有发烧，也没有咯血。书上有没有能用的方子？
```

会得到：一道主方（方名＋原料＋三步做法＋原书用法）→ 采购清单（药店 / 菜市场分组）→ 绿/黄/红判断 → 两个追问方向。

## 安全设计

三层拦截，任何一层命中都会改变回答形态：

| 层 | 触发 | 行为 |
| --- | --- | --- |
| 急症 | 胸痛、呼吸困难、晕厥、抽搐、大出血、误服中毒等 | 不检索、不给方，只给就医指引 |
| 重症 | 尿毒症、白血病、肝硬化、肺结核、冠心病、肠梗阻等 | 就医优先，方剂仅作资料参考 |
| 药材 | 高毒（雄黄、轻粉、巴豆…）／需炮制（附子、半夏…）／需注意（酒、甘草、糖…） | 分别降级为「不可自行配制」「须药师确认」「按提示核对」 |

此外，孕期、备孕、哺乳、婴幼儿、糖尿病、高血压、肝病、肾病、长期服药、抗凝药等情况一律先问医师或药师。

### 检索可信度（v1.2）

**找不到就说找不到。** 这是 v1.2 的核心修复。

此前 `run_search` 有一个静默兜底：没有匹配到病症时，仍然返回得分最高的几条记录。结果是一组真实口语提问里，**25 条只有 5 条找对，其余 20 条拿到了完全无关的方子且不报错**：

| 用户说 | 修复前返回 |
| --- | --- |
| 三天没上厕所了 | 火腿爪甲鸡内金**治水肿** |
| 晚上翻来覆去睡不着 | 芹菜苗**治疗百日咳** |
| 头发掉得厉害 | 金针菜木耳发灰**治疗便血** |
| 被开水烫了 | 拌菠菜海蜇**解头痛面赤** |

修复后：**22/25 命中**，其余 3 条（腰酸、眼睛干涩、风湿关节疼）原书确实没有对应小节，改为明确说「没找到」并给出候选方向。

具体做了三件事：

1. **取消静默兜底**，加 `no_match` 模式；未命中时把最接近的病症作为**问句**给用户挑，而不是当答案给。
2. **口语映射从 113 个病症扩到 232 个（100%）**，546 条短语，0 条死映射。含模糊匹配（「嘴里溃疡」能匹配「嘴里老是溃疡」）和儿科语境加权（「孩子半夜哭闹」→ 小儿夜啼，而不是成人失眠）。
3. **修复 6 个整节丢失的病症**：标题字号阈值卡得太紧，`便血`、`浮肿、腹水`、`麦粒肿`、`牙痛`、`湿疹`、`减肥轻身` 六个小节的标题（h=0.0239）差 0.0001 被拒，整节记录被挂到上一节名下。阈值调整为 0.023 后全部找回，共 100 条记录重新归类。

这 25 条真实口语提问已固化为回归测试（`tests/test_retrieval.py`），作为后续版本的验收底线。

### 个人用药档案闸门（v1.1）

前三层回答的是「这道方本身危不危险」。档案闸门回答的是**「这道方对你危不危险」**。

建一次档案（慢性病、长期在吃的西药、过敏史、孕期等），之后每轮回答自动过闸：

```bash
python3 scripts/profile.py \
  --conditions "高血压" --medications "氨氯地平" --allergies "蜂蜜"
```

- **换方而不是静默跳过。** 主方与登记情况冲突时自动改用下一道未冲突的方，并说明为什么换。
- **全部冲突就不给方。** 这一节所有候选都被拦下时，只列出原因，让你带着去问药师。
- **外用方单独判定。** 原书把内服方和外用方混在一节里，`麻黄外用` 是贴穴位的膏药而不是汤剂，按同一标准处理会两头都错。
- **识别不了的药明确说「未评估」**，不猜。

档案存在 `~/.miaoyong-pianfang-mifang/profile.json`（权限 `0600`），**只存本机**——本包所有脚本都不发网络请求。一条命令清除：

```bash
python3 scripts/profile.py --clear
```

细节见 [`references/personal-profile.md`](references/personal-profile.md)。

## 快速开始

```bash
# 按症状检索
python3 scripts/search.py --query "老是咳嗽痰多" --limit 3

# 生成完整回答卡（查方 + 用法整理 + 采购清单 + 安全分级）
python3 scripts/improve.py --issue "老便秘，三四天一次"

# 来源追溯
python3 scripts/format_answer.py --query "便血" --fields title,book_page

# 统计
python3 scripts/search.py --stats

# 个人用药档案
python3 scripts/profile.py --show
python3 scripts/profile.py --conditions "高血压" --medications "氨氯地平"
python3 scripts/profile.py --clear

# 自检
python3 -m unittest discover -s tests -p 'test_*.py'

# 发布到 SkillHub（需要个人 API Token）
export SKILLHUB_KEY=skh_xxx
python3 scripts/publish_skillhub.py --dir . --dry-run
python3 scripts/publish_skillhub.py --dir . --changelog "本次变更说明"
```

仅依赖 Python 3.9+ 标准库。

## 数据说明

| 指标 | 数值 |
| --- | --- |
| 原书页数 | 406 |
| 章节 | 8 |
| 病症条目 | 232 |
| 方剂记录 | 2395 |
| 三字段（原料/制用法/效用）齐全 | 2369（98.9%） |
| 原书未列方名 | 180 |
| 页码经页脚确认 | 1697（71%） |
| 口语映射覆盖 | 232 / 232（100%） |
| 真实口语提问命中 | 22 / 25 |

- 全书前序 10 页，故 `book_page = pdf_page − 10`，偏移由 308 个页脚可读页面交叉确定。
- 全部记录为**机器来源核对**，确认 OCR 转录与原页一致；**无人工逐条复核**。
- 来源核对不代表临床有效性或安全性评价。

重建流程见 [`references/maintenance.md`](references/maintenance.md)，来源与页码细节见 [`references/source-guide.md`](references/source-guide.md)。

## 版权

本仓库公开内容由资料权利方授权发布，仅包含结构化字段与原创代码文档，不含原始 PDF 与整页图像。原书著作权归原作者及出版方所有。

代码以 MIT 协议开源，见 [LICENSE](LICENSE)。

## 免责声明

本项目为资料整理工具，不提供医疗建议。任何身体不适请咨询执业医师或药师。使用本 Skill 输出的任何信息前，请先取得专业意见。
