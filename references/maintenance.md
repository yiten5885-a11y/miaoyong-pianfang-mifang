# 数据重建与维护

本页用于维护 Skill 包，不用于回答用户问题。所有命令都从项目根目录运行。

## 依赖

- Python 3.9+（标准库即可，检索与编排脚本无第三方依赖）
- 重建 OCR 需要 macOS（Vision 框架）与 Xcode 命令行工具

## 目录

```text
miaoyong-pianfang-mifang/
├── SKILL.md                  主指令
├── README.md                 项目说明
├── manifest.yaml             技能市场元数据
├── cover.png                 封面图（AI 生成原创）
├── assets/
│   ├── records.jsonl         全量方剂记录（2395 条）
│   └── toc.json              原书目录（8 章 230 条）
├── references/               规则与话术文档
├── scripts/
│   ├── ocr_vision.swift      扫描页 OCR（macOS Vision）
│   ├── run_ocr.sh            并行 OCR 驱动
│   ├── build_records.py      OCR → records.jsonl / toc.json
│   ├── safety.py             风险词库与安全判定
│   ├── interactions.py       药材×药物×疾病×特殊状态相互作用规则表
│   ├── profile.py            本地个人用药档案（读写 + CLI）
│   ├── search.py             确定性检索
│   ├── improve.py            回答编排（查方 + 用法整理 + 档案闸门）
│   ├── format_answer.py      来源追溯模式
│   └── publish_skillhub.py   SkillHub 发布工具（支持图标）
└── tests/
    ├── test_records.py       数据结构自检
    ├── test_profile.py       档案与闸门自检
    └── test_retrieval.py     检索回归（25 条真实口语用例）
```

## 从原始 PDF 重建

```bash
# 1. 编译 OCR 工具
swiftc -O -o /tmp/ocr_vision scripts/ocr_vision.swift

# 2. 并行 OCR（6 路，倍率 2.2）
bash scripts/run_ocr.sh "<原书.pdf>" 1 406 6 data/ocr 2.2

# 3. 解析为结构化记录
python3 scripts/build_records.py

# 4. 自检
python3 -m unittest discover -s tests -p 'test_*.py'
```

重建后的守恒量（若不一致，先查明原因，不得直接覆盖）：

| 指标 | 期望值 |
| --- | --- |
| OCR 页数 | 406 |
| 记录数 | 2395 |
| 章节数 | 8 |
| 病症数 | 225 |
| 目录条目 | 230 |
| 前序偏移 | 10 |
| 三字段齐全 | 2369 |
| 口语映射 | 232/232 病症，546 条短语 |
| 口语回归命中 | ≥22/25 |
| 清洗后药材名 | 896 个（raw 1135） |

## 常用自检

```bash
python3 scripts/search.py --stats
python3 scripts/search.py --list-conditions
python3 scripts/search.py --query "咳嗽痰多" --limit 3
python3 scripts/improve.py --issue "老便秘，三四天一次"
python3 scripts/format_answer.py --query "便血" --fields title,book_page
```

## 修改可信度分层

- 打分维度：`scripts/trust.py` 的 `trust_score`（方名 +1、证型 +2、剂量 +1、
  三字段 +1）。改维度后必须跑 `python3 -m unittest tests.test_trust`——
  它守住五档分布与容差，某档漂移超 25% 会失败。
- 分档描述：`LEVELS` 字典。描述面向用户，**不得**出现分数数字。
- 候选池大小：`improve.py` 的 `pool_size`（当前 max(limit*3, 9)）。太小则
  记载最全的方进不了池子，太大则闸门开销上升。

## 修改药材清洗

- 规则在 `scripts/herbs.py`：剥「各」尾缀（全书系统性 OCR 现象）、剔除
  纯泛称（调料/味精/湿淀粉/作料/配料/佐料）、丢弃长度<2 的名字。
- **生/熟/干不在制法前缀表里**——「生姜」「干姜」「熟地」「生大黄」都是
  完整药名，无脑剥会削成单字丢弃。只有炙/炒/煅/鲜这类明确加工标记才剥。
- 白糖/黄酒/蜂蜜/葱白**不是**噪声，是药膳方真实辅料，不得加入剔除表。
- 新增噪声词后跑 `python3 -m unittest tests.test_herbs` 与
  `noise_report()` 核对清洗效果。

## 修改儿童闸门

- 儿童语境标记：`scripts/pediatric.py` 的 `CHILD_MARKERS`（与 search.py
  的 CHILD_MARKERS 保持一致，儿科加权也用）。
- 症状族→儿科小节映射：`SYMPTOM_FAMILY_TO_PEDIATRIC`。新增儿科小节时
  同步更新，并跑 `tests/test_pediatric.py` 的
  `test_common_parent_phrasings_route_to_pediatrics`。
- **红线**：闸门只警示，不折算剂量。任何版本都不得引入「按成人剂量
  乘以系数」的逻辑。

## 修改辨识要点

- 易混对表：`scripts/herb_id.py` 的 `CONFUSED_HERBS`。新增条目必须
  在语料中真实出现（测试会校验）。
- 泛称与具体名去重：关键词按长度降序匹配（川贝母先于贝母），
  泛称条目在具体名命中后跳过。
- 措辞红线：客观描述，禁止「假的」「伪品」判定式表述（测试会校验）。

## 修改检索

- 口语映射：`scripts/search.py` 的 `SYNONYMS`。新增后必须跑
  `python3 -m unittest tests.test_retrieval` —— 它会校验**没有死映射**
  （目标病症必须真实存在）且**每个病症都可到达**。
- 模糊匹配容差：同文件 `fuzzy_contains`，当前允许短语长度以内的填充字符。
- 儿科语境词：`CHILD_MARKERS`，用于把 `小儿*` 小节与成人同名小节区分开。
- 建议算法：`suggest_conditions`，要求病症名有 2 字重叠，或正文重叠 ≥3，
  避免单字噪声产生离谱建议。
- 新增真实口语用例时，直接加进 `tests/test_retrieval.py` 的 `CASES`。

## 修改风险词库

- 药材风险等级：`scripts/safety.py` 的 `RISK_HERBS`，同时同步 `references/toxic-herbs.md` 的表格。
- 急症词：`scripts/safety.py` 的 `EMERGENCY_TERMS`。
- 用户侧红线：`scripts/safety.py` 的 `RED_FLAGS`。
- 重症清单：`scripts/safety.py` 的 `SERIOUS_CONDITIONS`。
- 症状同义词：`scripts/search.py` 的 `SYNONYMS`。

改完跑一遍 `python3 -m unittest discover -s tests -p 'test_*.py'`。

## 版本

- `1.4.0`：儿童剂量安全层 + 易混药材辨识。新增 `scripts/pediatric.py`：
  识别儿童语境（孩子/宝宝/婴儿/几岁），命中小节属成人章节时输出闸门
  （警示成人剂量不能套儿童、指引儿科小节或就医，方照给不折算）；
  补齐 20+ 条儿科口语映射（咳嗽→小儿咳喘、拉肚子→小儿泄泻等）。
  新增 `scripts/herb_id.py` + `references/herb-id.md`：12 个易混药材
  （川贝母/浙贝母、牛膝/川牛膝、茯苓/猪苓…）辨识要点，覆盖 192 条记录。
  新增 `tests/test_pediatric.py`（14 项）、`tests/test_herb_id.py`（12 项）。
- `1.3.0`：来源可信度分层 + 药材名清洗。新增 `scripts/trust.py`（按原书字段
  完整度打 0-5 分，五档分布 {1:16, 2:620, 3:1155, 4:104, 5:500}）与
  `scripts/herbs.py`（剥 OCR「各」字粘连 474 处、剔除纯泛称，清洗后 896 个
  药材名）；候选池放大到 max(limit*3, 9)，按完整度优先排序后截断，防止
  记载最全的方进不了 limit 之内的池子；新增 `tests/test_trust.py`（22 项）
  与 `tests/test_herbs.py`（21 项）。清洗只在解析层，不改原文转录。
- `1.2.0`：检索可信度。取消 `run_search` 的静默兜底，新增 `no_match` 模式与候选建议；
  口语映射扩到 232/232 病症（546 条，0 死映射），加模糊匹配与儿科语境加权；
  修复 6 个整节丢失的病症（字号阈值 0.024 → 0.023）与 4.1% 的章节错标；
  新增 `tests/test_retrieval.py`（25 条真实口语回归集）。
- `1.1.0`：S3 个人用药档案与相互作用闸门。新增 `scripts/interactions.py`（四类规则）、
  `scripts/profile.py`（本地档案读写与 CLI）、`tests/test_profile.py`（28 项）；
  `improve.py` 增加闸门与自动换方；`--profile-json` / `--no-profile` 参数。
- `1.0.2`：补充获取方式与发布文档；新增 SkillHub 直连发布工具。
- `1.0.1`：补充 SkillHub 发布工具与封面图标；上架 SkillHub。
- `1.0.0`：首次发布。406 页全量 OCR，2395 条结构化记录，8 章 225 病症。

## 修改相互作用规则

- 规则表：`scripts/interactions.py` 的 `INTERACTION_RULES`，每条必须含 `id` / `herbs` /
  `triggers` / `level` / `reason` / `action`，测试会校验完整性。
- 药物词表：同文件 `DRUG_CLASSES`，按子串匹配，商品名与通用名都加进去。
- 同名遮蔽：`SHADOWING_NAMES`，用于「麻黄根 ≠ 麻黄」这类必须区分的药。
- 给药途径标记：`EXTERNAL_MARKERS` / `INTERNAL_MARKERS`。
- 改完同步更新 `references/personal-profile.md` 的覆盖范围表，并跑测试。

## 发布到 SkillHub

已上架：https://skillhub.cn/skills/miaoyong-pianfang-mifang
（canonical name `@user_a007d674/miaoyong-pianfang-mifang`）

### 用官方 CLI

```bash
curl -fsSL https://skillhub.cn/install/install.sh | bash -s -- --cli-only
skillhub login --key "$SKILLHUB_KEY" --host https://api.skillhub.cn
skillhub publish . --host https://api.skillhub.cn --dry-run
skillhub publish . --host https://api.skillhub.cn --changelog "本次变更"
```

### 用本仓库的发布工具（支持上传图标）

官方 CLI 不会上传技能头像（无 `iconUrl` 时用默认占位图），且会打包 `data/`
目录。`scripts/publish_skillhub.py` 补上了这两点：

```bash
export SKILLHUB_KEY=skh_xxx          # 个人中心 → API keys
python3 scripts/publish_skillhub.py --dir . --dry-run
python3 scripts/publish_skillhub.py --dir . --changelog "本次变更"
```

### 发布链路要点（实测）

- 端点：`POST https://api.skillhub.cn/api/v1/community/skills/publish`，鉴权
  `Authorization: Bearer skh_...`。
- 请求体是 multipart：`payload` 必须是**无 filename 的表单字段**（带上
  filename 会报「缺少 payload 字段」），文件用重复的 `files` 字段，其
  filename 即相对路径。
- `payload` 字段：`slug` / `displayName` / `version` / `summaryZh` /
  `changelog` / `iconUrl` / `category` / `subCategories`。
- 图标另走 `POST /api/v1/community/skill-icons/upload`（字段 `file`），返回
  `iconUrl` 后再带进 `payload`。
- **服务端按扩展名允许列表校验**：`LICENSE`（无扩展名）会直接 400
  「不允许的文件类型」；图片也不允许进包，只能作为 `iconUrl`。
- 包体上限 10 MB；`slug` 全网唯一且 kebab-case；同一版本号重复发布会 409，
  必须升版本。
- 发布后进入审核：`reviewStatus` / `contentAuditStatus` / `iconAuditStatus` /
  `securityScanStatus` 均为 `pending`，通过后公开详情页才显示版本与图标。

## 升级与卸载

本包为静态 Skill，无安装脚本。宿主平台（WorkBuddy / SkillHub）负责加载与更新。卸载时直接移除技能目录即可，不涉及系统级写入。

## 注意

- `data/` 目录是 OCR 中间产物，**不随仓库发布**（体积大且含原书全文行级转录）。
- 公开发布的 `assets/records.jsonl` 是结构化后的方剂字段，不含整页图像。
- 重建数据不能替代独立人工复核。
