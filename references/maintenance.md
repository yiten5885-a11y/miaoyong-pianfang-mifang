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
│   ├── search.py             确定性检索
│   ├── improve.py            回答编排（查方 + 用法整理）
│   └── format_answer.py      来源追溯模式
└── tests/
    └── test_records.py       结构自检
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

## 常用自检

```bash
python3 scripts/search.py --stats
python3 scripts/search.py --list-conditions
python3 scripts/search.py --query "咳嗽痰多" --limit 3
python3 scripts/improve.py --issue "老便秘，三四天一次"
python3 scripts/format_answer.py --query "便血" --fields title,book_page
```

## 修改风险词库

- 药材风险等级：`scripts/safety.py` 的 `RISK_HERBS`，同时同步 `references/toxic-herbs.md` 的表格。
- 急症词：`scripts/safety.py` 的 `EMERGENCY_TERMS`。
- 用户侧红线：`scripts/safety.py` 的 `RED_FLAGS`。
- 重症清单：`scripts/safety.py` 的 `SERIOUS_CONDITIONS`。
- 症状同义词：`scripts/search.py` 的 `SYNONYMS`。

改完跑一遍 `python3 -m unittest discover -s tests -p 'test_*.py'`。

## 版本

- `1.0.1`：补充 SkillHub 发布工具与封面图标；上架 SkillHub。
- `1.0.0`：首次发布。406 页全量 OCR，2395 条结构化记录，8 章 225 病症。

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
