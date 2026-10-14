#!/usr/bin/env python3
"""Safety lexicons and guards for the 妙用偏方秘方 reference skill.

Three independent jobs live here:

1. `EMERGENCY_TERMS`  — symptoms that must stop the whole flow and route the
   user to in-person care. Nothing is generated for these.
2. `RISK_HERBS`       — ingredients that carry a real toxicity or regulatory
   risk. Any formula containing one is downgraded to "do not self-prepare".
3. `RED_FLAGS`        — user conditions (pregnancy, chronic disease, children,
   polypharmacy) that make even a benign formula a pharmacist-first decision.

The lists are deliberately conservative. They are reference material, not a
substitute for a pharmacist's review of the specific formula.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 1. Acute presentation — stop, do not generate a formula.
# --------------------------------------------------------------------------
EMERGENCY_TERMS: dict[str, list[str]] = {
    "意识与神经": [
        "昏迷", "晕厥", "抽搐", "抽风", "意识不清", "说胡话", "瘫痪",
        "口眼歪斜", "突然失语", "剧烈头痛",
    ],
    "心肺": [
        "胸痛", "胸闷压榨", "呼吸困难", "喘不上气", "心跳很快", "心慌不止",
        "咯血", "大量出血", "吐血",
    ],
    "急腹症": [
        "剧烈腹痛", "肚子痛得直不起腰", "腹部拒按", "呕血", "便血不止",
        "黑便", "剧烈呕吐",
    ],
    "外伤与中毒": [
        "外伤", "骨折", "大出血", "误服", "中毒", "农药", "蛇咬", "狂犬",
    ],
    "妇产急症": [
        "孕早期出血", "怀孕期间出血", "孕期腹痛", "胎动消失", "临产",
    ],
    "儿科急症": [
        "婴儿高热", "新生儿黄疸加重", "小儿抽搐", "小儿意识不清",
        "小儿脱水",
    ],
}

# --------------------------------------------------------------------------
# 2. Ingredient risk tiers.
#    high   -> never suggest self-preparation, pharmacist/hospital only
#    medium -> only with a pharmacist's confirmation of dose and processing
#    caution-> common but needs a specific warning (alcohol, strong purgatives)
# --------------------------------------------------------------------------
RISK_HERBS: dict[str, dict[str, str]] = {
    # --- high: classical toxic / heavy-metal / regulated substances ---
    "砒霜": {"level": "high", "why": "砷化物，治疗量与中毒量接近"},
    "信石": {"level": "high", "why": "砷化物，治疗量与中毒量接近"},
    "雄黄": {"level": "high", "why": "含砷，加热后毒性增大"},
    "雌黄": {"level": "high", "why": "含砷"},
    "水银": {"level": "high", "why": "汞，蓄积中毒"},
    "轻粉": {"level": "high", "why": "汞制剂"},
    "粉霜": {"level": "high", "why": "汞制剂"},
    "红升丹": {"level": "high", "why": "汞制剂"},
    "白降丹": {"level": "high", "why": "汞制剂"},
    "铅丹": {"level": "high", "why": "铅，蓄积中毒"},
    "密陀僧": {"level": "high", "why": "含铅"},
    "樟丹": {"level": "high", "why": "含铅"},
    "马钱子": {"level": "high", "why": "番木鳖碱，安全窗口极窄"},
    "番木鳖": {"level": "high", "why": "番木鳖碱，安全窗口极窄"},
    "巴豆": {"level": "high", "why": "峻猛泻下，可致脱水与出血"},
    "千金子": {"level": "high", "why": "峻下逐水，毒性大"},
    "甘遂": {"level": "high", "why": "峻下逐水，毒性大"},
    "大戟": {"level": "high", "why": "峻下逐水，毒性大"},
    "京大戟": {"level": "high", "why": "峻下逐水，毒性大"},
    "芫花": {"level": "high", "why": "峻下逐水，毒性大"},
    "商陆": {"level": "high", "why": "峻下逐水，毒性大"},
    "狼毒": {"level": "high", "why": "毒性大，多外用"},
    "藤黄": {"level": "high", "why": "毒性大，多外用"},
    "雷公藤": {"level": "high", "why": "肝肾与生殖毒性"},
    "斑蝥": {"level": "high", "why": "发疱剂，肾毒性"},
    "芫青": {"level": "high", "why": "同斑蝥类"},
    "红娘子": {"level": "high", "why": "同斑蝥类"},
    "蟾酥": {"level": "high", "why": "强心苷样毒性"},
    "洋金花": {"level": "high", "why": "曼陀罗类，抗胆碱能中毒"},
    "曼陀罗": {"level": "high", "why": "抗胆碱能中毒"},
    "天仙子": {"level": "high", "why": "莨菪碱类"},
    "生川乌": {"level": "high", "why": "乌头碱，须严格炮制"},
    "生草乌": {"level": "high", "why": "乌头碱，须严格炮制"},
    "生附子": {"level": "high", "why": "乌头碱，须严格炮制"},
    "生半夏": {"level": "high", "why": "须炮制，生品刺激性强"},
    "生南星": {"level": "high", "why": "须炮制，生品刺激性强"},
    "生白附子": {"level": "high", "why": "须炮制"},
    "罂粟壳": {"level": "high", "why": "麻醉药品管制，长期用可成瘾"},
    "木鳖子": {"level": "high", "why": "毒性大，多外用"},
    "藜芦": {"level": "high", "why": "与诸参相反，毒性大"},
    "硫黄": {"level": "high", "why": "内服须极严格炮制"},

    # --- medium: usable, but dose/processing must be confirmed ---
    "附子": {"level": "medium", "why": "乌头碱类，须炮制并先煎"},
    "川乌": {"level": "medium", "why": "乌头碱类，须炮制"},
    "草乌": {"level": "medium", "why": "乌头碱类，须炮制"},
    "乌头": {"level": "medium", "why": "乌头碱类，须炮制"},
    "半夏": {"level": "medium", "why": "须用制半夏，生品有毒"},
    "南星": {"level": "medium", "why": "须用制南星"},
    "白附子": {"level": "medium", "why": "须用制品"},
    "细辛": {"level": "medium", "why": "含马兜铃酸，不宜长期大量"},
    "朱砂": {"level": "medium", "why": "含汞，不宜久服"},
    "辰砂": {"level": "medium", "why": "含汞，不宜久服"},
    "麻黄": {"level": "medium", "why": "高血压、心脏病、失眠者慎用"},
    "苦杏仁": {"level": "medium", "why": "含氰苷，须炒制且不过量"},
    "桃仁": {"level": "medium", "why": "含氰苷，孕妇慎用"},
    "白果": {"level": "medium", "why": "含银杏酸，须熟制且限量"},
    "马兜铃": {"level": "medium", "why": "肾毒性，已限用"},
    "关木通": {"level": "medium", "why": "马兜铃酸肾毒性"},
    "广防己": {"level": "medium", "why": "马兜铃酸肾毒性"},
    "蜈蚣": {"level": "medium", "why": "虫类药，须规范炮制"},
    "全蝎": {"level": "medium", "why": "虫类药，须规范炮制"},
    "水蛭": {"level": "medium", "why": "抗凝作用，出血倾向者禁用"},
    "虻虫": {"level": "medium", "why": "破血峻药，孕妇禁用"},
    "麝香": {"level": "medium", "why": "孕妇禁用"},

    # --- caution: common, but needs an explicit warning ---
    "黄酒": {"level": "caution", "why": "含酒精，肝病、孕妇、服药者注意"},
    "白酒": {"level": "caution", "why": "含酒精，肝病、孕妇、服药者注意"},
    "米酒": {"level": "caution", "why": "含酒精，肝病、孕妇、服药者注意"},
    "酒": {"level": "caution", "why": "含酒精，肝病、孕妇、服药者注意"},
    "大黄": {"level": "caution", "why": "泻下，孕妇与体虚者慎用"},
    "芒硝": {"level": "caution", "why": "泻下，孕妇慎用"},
    "番泻叶": {"level": "caution", "why": "泻下，不宜久用"},
    "甘草": {"level": "caution", "why": "长期大量可致水肿、低血钾"},
    "蜂蜜": {"level": "caution", "why": "1 岁以下婴儿禁用"},
    "红糖": {"level": "caution", "why": "糖尿病患者注意"},
    "白糖": {"level": "caution", "why": "糖尿病患者注意"},
}

# --------------------------------------------------------------------------
# 3. User-side red flags.
# --------------------------------------------------------------------------
RED_FLAGS: dict[str, str] = {
    "怀孕": "孕期用药须由产科或中医师当面评估，本方不作自用建议。",
    "备孕": "备孕期建议先经医师评估，避免使用活血、峻下或有生殖毒性的药材。",
    "哺乳": "哺乳期成分可经乳汁影响婴儿，须先咨询医师。",
    "婴幼儿": "婴幼儿剂量与成人差异极大，不得按成人方折算。",
    "儿童": "儿童用药须由儿科或中医师按体重与年龄调整。",
    "老人": "老年人肝肾功能下降，剂量与相互作用风险更高。",
    "糖尿病": "方中含糖或含淀粉类辅料时须先核对血糖影响。",
    "高血压": "含麻黄等升压成分时须先咨询医师。",
    "肝病": "含酒精或经肝代谢的药材须先咨询医师。",
    "肾病": "须先排除马兜铃酸类等肾毒性药材。",
    "长期服药": "与处方药可能存在相互作用，须由药师核对。",
    "抗凝": "含活血化瘀类药材可能增加出血风险。",
    "过敏": "须逐味核对原料过敏史。",
    "胃溃疡": "刺激性或泻下类药材可能加重症状。",
    "蚕豆病": "须避开蚕豆及部分氧化性药材。",
}

# Words that mean "the user wants to know what the book says", not "give me a
# protocol". Used by the answer layer to decide the response shape.
TRACE_TERMS = ["页码", "第几页", "原文", "原书", "出处", "记录", "来源", "证据", "怎么核对的"]


def scan_emergency(text: str) -> list[str]:
    """Return the emergency phrases present in the user's message."""
    hits: list[str] = []
    for phrases in EMERGENCY_TERMS.values():
        for phrase in phrases:
            if phrase in text and phrase not in hits:
                hits.append(phrase)
    return hits


def scan_red_flags(text: str) -> list[str]:
    """Return the user-side red flags present in the user's message."""
    return [flag for flag in RED_FLAGS if flag in text]


def scan_herbs(text: str) -> list[dict]:
    """Return risk annotations for every risky ingredient in a formula string.

    Longest match wins so that 生川乌 is not reported as plain 川乌.
    """
    found: dict[str, dict] = {}
    for name in sorted(RISK_HERBS, key=len, reverse=True):
        if name in text:
            if any(name in existing for existing in found):
                continue
            found[name] = {"herb": name, **RISK_HERBS[name]}
    order = {"high": 0, "medium": 1, "caution": 2}
    return sorted(found.values(), key=lambda item: order[item["level"]])


# --------------------------------------------------------------------------
# 4. Conditions where the book's own remedies must never be framed as a
#    treatment plan: these need supervised medical care, and the entry is
#    presented as reference material only.
# --------------------------------------------------------------------------
SERIOUS_CONDITIONS: dict[str, str] = {
    "尿毒症": "肾功能衰竭，须透析或专科治疗，不得以偏方替代。",
    "白血病": "血液系统恶性肿瘤，须血液科规范治疗。",
    "再生障碍性贫血": "须血液科规范治疗，偏方不能替代。",
    "肝硬化": "须肝病专科随访，部分草药反而加重肝损伤。",
    "肝炎": "病毒性肝炎须明确病因后规范治疗。",
    "肺结核": "须抗结核规范全程治疗，中断会耐药。",
    "肺炎": "细菌性肺炎须抗生素治疗，延误有风险。",
    "肺脓肿": "须抗感染与引流，偏方不能替代。",
    "肾结核": "须抗结核治疗。",
    "肾病综合征": "须肾内科评估，蛋白尿与水肿不宜自行处理。",
    "肾盂肾炎": "须抗感染治疗。",
    "冠心病": "须心内科评估，胸痛发作须急诊。",
    "心力衰竭": "须心内科规范治疗。",
    "心律失常": "须先明确类型，部分类型有猝死风险。",
    "心肌炎": "病毒性心肌炎须卧床与专科治疗。",
    "风湿性心脏病": "须心内科随访。",
    "肺原性心脏病": "须呼吸与心内科联合管理。",
    "脑中风": "急性期须急诊溶栓，后遗症期须康复科介入。",
    "癫痫": "须神经内科规范用药，不可自行停药。",
    "精神分裂症": "须精神科规范治疗。",
    "抑郁性神经症": "中重度须精神科评估，偏方不能替代。",
    "甲状腺机能亢进症": "须内分泌科治疗，含碘药材需谨慎。",
    "甲状腺机能减退症": "须内分泌科替代治疗。",
    "糖尿病": "须内分泌科管理血糖，偏方不能替代降糖方案。",
    "高血脂症": "须评估心血管风险后规范干预。",
    "血小板减少症": "须血液科评估出血风险。",
    "白细胞减少症": "须查明原因。",
    "肠梗阻": "可能需急诊处理，禁止自行服泻药。",
    "阑尾炎": "须外科评估，延误可致穿孔。",
    "破伤风": "须急诊处理。",
    "脑震荡": "须排除颅内出血。",
    "蛇咬伤": "须急诊抗蛇毒血清。",
    "水火烫伤": "大面积或深部烫伤须急诊处理。",
    "小儿惊风": "须儿科急诊排查病因。",
    "妊娠高血压": "须产科管理。",
    "先兆流产": "须产科评估，禁止自行用药。",
    "习惯性流产": "须产科与生殖专科评估。",
    "子宫出血": "须妇科评估出血原因。",
    "崩漏": "出血量大或持续须妇科评估。",
    "尿血": "须先排除泌尿系肿瘤与结石。",
    "便血": "须先排除消化道肿瘤与溃疡出血。",
    "咯血": "须呼吸科评估。",
    "乳糜尿": "须查明病因。",
    "白血病细胞浸润": "须血液科治疗。",
}


def scan_serious(condition: str) -> str | None:
    if not condition:
        return None
    for name, note in SERIOUS_CONDITIONS.items():
        if name in condition:
            return note
    return None


def worst_level(herbs: list[dict]) -> str:
    if not herbs:
        return "none"
    return herbs[0]["level"]
