#!/usr/bin/env python3
"""Personalised interaction layer: herb x medication x condition x special state.

This is the module behind S3. It answers a different question from
`references/toxic-herbs.md`:

  * `safety.py`  — "is this formula dangerous on its own?"
  * `interactions.py` — "is this formula dangerous **for this person**?"

Design rules
------------
1. **Conservative by construction.** Only well-established interactions are
   listed. A false negative is far cheaper than a false positive here: telling
   someone to skip a harmless formula costs them a remedy, telling them a
   dangerous one is fine costs them their health.
2. **Rule = herbs x triggers.** A rule fires only when the formula actually
   contains one of the herbs *and* the user's profile matches one of the
   triggers. Neither side alone is enough.
3. **Never a diagnosis.** Triggers match the user's own words. We do not infer
   a condition they did not state.
4. **Never a substitute for a pharmacist.** Every rule carries an `action`
   that routes to a professional when the stakes warrant it.

The drug lexicon is deliberately name-based rather than class-based on the
input side: users type "氨氯地平", not "calcium channel blocker".
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Drug name -> class. Extend freely; matching is substring based so brand and
# generic names both work.
# ---------------------------------------------------------------------------
DRUG_CLASSES: dict[str, list[str]] = {
    "antihypertensive": [
        "氨氯地平", "硝苯地平", "非洛地平", "尼群地平", "左旋氨氯地平",
        "缬沙坦", "氯沙坦", "厄贝沙坦", "替米沙坦", "奥美沙坦",
        "依那普利", "卡托普利", "贝那普利", "培哚普利", "福辛普利",
        "美托洛尔", "比索洛尔", "阿替洛尔", "普萘洛尔", "卡维地洛",
        "氢氯噻嗪", "吲达帕胺", "呋塞米", "螺内酯", "特拉唑嗪",
        "降压药", "血压药",
    ],
    "anticoagulant": [
        "华法林", "阿司匹林", "氯吡格雷", "替格瑞洛", "普拉格雷",
        "利伐沙班", "阿哌沙班", "达比加群", "依诺肝素", "肝素",
        "双嘧达莫", "西洛他唑", "抗凝", "抗血小板", "薄血药",
    ],
    "antidiabetic": [
        "二甲双胍", "格列美脲", "格列齐特", "格列吡嗪", "格列本脲",
        "阿卡波糖", "伏格列波糖", "西格列汀", "维格列汀", "沙格列汀",
        "达格列净", "恩格列净", "卡格列净", "吡格列酮", "罗格列酮",
        "胰岛素", "降糖药", "血糖药",
    ],
    "statin": [
        "阿托伐他汀", "瑞舒伐他汀", "辛伐他汀", "普伐他汀",
        "氟伐他汀", "匹伐他汀", "他汀", "降脂药",
    ],
    "digoxin": ["地高辛", "洋地黄", "西地兰", "去乙酰毛花苷"],
    "diuretic": [
        "呋塞米", "氢氯噻嗪", "吲达帕胺", "螺内酯", "托拉塞米",
        "布美他尼", "利尿剂", "利尿药",
    ],
    "potassium_sparing": [
        "螺内酯", "氨苯蝶啶", "阿米洛利",
        "缬沙坦", "氯沙坦", "厄贝沙坦", "替米沙坦", "奥美沙坦",
        "依那普利", "卡托普利", "贝那普利", "培哚普利", "福辛普利",
    ],
    "antiepileptic": [
        "卡马西平", "丙戊酸钠", "苯妥英钠", "拉莫三嗪", "左乙拉西坦",
        "奥卡西平", "加巴喷丁", "普瑞巴林", "抗癫痫",
    ],
    "psychotropic": [
        "舍曲林", "帕罗西汀", "氟西汀", "西酞普兰", "文拉法辛",
        "度洛西汀", "米氮平", "奥氮平", "氯氮平", "喹硫平", "利培酮",
        "阿普唑仑", "地西泮", "劳拉西泮", "艾司唑仑", "佐匹克隆",
        "唑吡坦", "碳酸锂", "锂盐", "抗抑郁", "安眠药", "镇静药",
    ],
    "maoi": ["苯乙肼", "异卡波肼", "反苯环丙胺", "吗氯贝胺", "司来吉兰"],
    "thyroid": [
        "左甲状腺素", "优甲乐", "甲巯咪唑", "丙硫氧嘧啶", "甲状腺片",
        "甲亢药", "甲减药",
    ],
    "nitroimidazole": ["甲硝唑", "替硝唑", "奥硝唑", "塞克硝唑"],
    "cephalosporin": [
        "头孢", "头孢克肟", "头孢拉定", "头孢呋辛", "头孢地尼",
        "头孢曲松", "头孢氨苄", "头孢克洛",
    ],
    "quinolone_tetracycline": [
        "左氧氟沙星", "氧氟沙星", "莫西沙星", "环丙沙星", "诺氟沙星",
        "四环素", "多西环素", "米诺环素",
    ],
    "immunosuppressant": ["他克莫司", "环孢素", "西罗莫司", "吗替麦考酚酯"],
    "corticosteroid": [
        "泼尼松", "强的松", "甲泼尼龙", "地塞米松", "氢化可的松",
        "倍他米松", "激素", "糖皮质激素",
    ],
    "anticholinergic": [
        "阿托品", "山莨菪碱", "东莨菪碱", "苯海索", "托特罗定",
        "索利那新", "奥昔布宁",
    ],
}


def normalize_drugs(entries: list[str]) -> list[str]:
    """Map free-text medication names onto drug classes (plus the raw names)."""
    classes: list[str] = []
    for entry in entries:
        text = str(entry).strip()
        if not text:
            continue
        for klass, names in DRUG_CLASSES.items():
            if any(name in text for name in names):
                if klass not in classes:
                    classes.append(klass)
    return classes


def unknown_drugs(entries: list[str]) -> list[str]:
    """Medications the lexicon could not classify — surfaced, never guessed at."""
    out: list[str] = []
    for entry in entries:
        text = str(entry).strip()
        if not text:
            continue
        if not any(name in text for _, names in DRUG_CLASSES.items()
                   for name in names):
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# Interaction rules.
#
#   herbs    : any one present in the formula triggers the rule
#   triggers : any one present in the profile triggers the rule
#   level    : "block"  -> drop the formula, offer an alternative
#              "warn"   -> keep it but state the interaction plainly
# ---------------------------------------------------------------------------
INTERACTION_RULES: list[dict] = [
    # ---- 麻黄 -------------------------------------------------------------
    {"id": "mahuang-antihtn", "herbs": ["麻黄"], "level": "block",
     "triggers": {"medications": ["antihypertensive"]},
     "reason": "麻黄含麻黄碱，会升高血压、加快心率，拮抗降压药效果。",
     "action": "换一道不含麻黄的方；确需使用请先咨询心内科医师。"},
    {"id": "mahuang-maoi", "herbs": ["麻黄"], "level": "block",
     "triggers": {"medications": ["maoi"]},
     "reason": "麻黄与单胺氧化酶抑制剂合用可诱发高血压危象。",
     "action": "不得合用，换方。"},
    {"id": "mahuang-digoxin", "herbs": ["麻黄"], "level": "block",
     "triggers": {"medications": ["digoxin"]},
     "reason": "麻黄加快心率，与强心苷合用增加心律失常风险。",
     "action": "换方；确需使用请先咨询心内科医师。"},
    {"id": "mahuang-htn", "herbs": ["麻黄"], "level": "block",
     "triggers": {"conditions": ["高血压"]},
     "reason": "麻黄升压，高血压人群不宜自行服用。",
     "action": "换一道不含麻黄的方。"},
    {"id": "mahuang-heart", "herbs": ["麻黄"], "level": "block",
     "triggers": {"conditions": ["冠心病", "心力衰竭", "心律失常", "心肌炎",
                                "风湿性心脏病", "肺原性心脏病", "心绞痛"]},
     "reason": "麻黄加快心率、增加心肌耗氧，心脏病人群风险高。",
     "action": "换方，并向心内科医师确认。"},
    {"id": "mahuang-hyperthyroid", "herbs": ["麻黄"], "level": "block",
     "triggers": {"conditions": ["甲状腺机能亢进", "甲亢"]},
     "reason": "甲亢本身交感兴奋，麻黄进一步加重心悸与血压升高。",
     "action": "换方。"},
    {"id": "mahuang-insomnia", "herbs": ["麻黄"], "level": "warn",
     "triggers": {"conditions": ["失眠", "神经衰弱"]},
     "reason": "麻黄有中枢兴奋作用，可能加重入睡困难。",
     "action": "避免睡前服用，或换方。"},
    {"id": "mahuang-bph", "herbs": ["麻黄"], "level": "warn",
     "triggers": {"conditions": ["前列腺增生", "前列腺肥大", "尿潴留"]},
     "reason": "麻黄可能加重排尿困难。",
     "action": "先咨询泌尿外科医师。"},

    # ---- 甘草 -------------------------------------------------------------
    {"id": "gancao-diuretic", "herbs": ["甘草"], "level": "block",
     "triggers": {"medications": ["diuretic"]},
     "reason": "甘草的类醛固酮作用叠加利尿剂，易致低血钾与水肿。",
     "action": "换方。"},
    {"id": "gancao-digoxin", "herbs": ["甘草"], "level": "block",
     "triggers": {"medications": ["digoxin"]},
     "reason": "甘草致低血钾，会显著增强强心苷毒性。",
     "action": "换方。"},
    {"id": "gancao-k", "herbs": ["甘草"], "level": "block",
     "triggers": {"medications": ["potassium_sparing"]},
     "reason": "甘草潴钠排钾，与保钾类药物合用有高血钾风险。",
     "action": "换方，或由医师监测血钾。"},
    {"id": "gancao-antihtn", "herbs": ["甘草"], "level": "warn",
     "triggers": {"medications": ["antihypertensive"]},
     "reason": "甘草水钠潴留会削弱降压效果。",
     "action": "不宜长期服用；服降压药期间先咨询医师。"},
    {"id": "gancao-steroid", "herbs": ["甘草"], "level": "warn",
     "triggers": {"medications": ["corticosteroid"]},
     "reason": "甘草与糖皮质激素合用加重水钠潴留与低血钾。",
     "action": "不宜长期合用。"},
    {"id": "gancao-hf", "herbs": ["甘草"], "level": "block",
     "triggers": {"conditions": ["心力衰竭", "高血压", "肾病综合征", "肾盂肾炎"]},
     "reason": "甘草致水钠潴留，会加重心衰、水肿与血压升高。",
     "action": "换方。"},

    # ---- 活血化瘀 x 抗凝 --------------------------------------------------
    {"id": "huoxue-anticoag", "level": "block",
     "herbs": ["丹参", "当归", "川芎", "红花", "桃仁", "水蛭", "三七",
               "赤芍", "益母草", "牛膝", "乳香", "没药", "蒲黄",
               "五灵脂", "延胡索", "莪术", "三棱", "苏木", "地鳖虫"],
     "triggers": {"medications": ["anticoagulant"]},
     "reason": "活血化瘀类药材与抗凝／抗血小板药叠加，出血风险明显上升。",
     "action": "换方；确需使用请先咨询开药医师并监测凝血。"},
    {"id": "huoxue-bleeding", "level": "block",
     "herbs": ["丹参", "当归", "川芎", "红花", "桃仁", "水蛭", "三七",
               "赤芍", "益母草", "牛膝", "莪术", "三棱", "苏木"],
     "triggers": {"conditions": ["血小板减少", "紫癜", "血友病", "崩漏",
                                "子宫出血", "胃溃疡"]},
     "reason": "已有出血倾向或活动性出血时，活血化瘀类药材可能加重出血。",
     "action": "换方，先处理原发病。"},

    # ---- 人参 / 黄芪 ------------------------------------------------------
    {"id": "renshen-antidiabetic", "herbs": ["人参"], "level": "warn",
     "triggers": {"medications": ["antidiabetic"]},
     "reason": "人参可能影响血糖，与降糖药合用需警惕低血糖或波动。",
     "action": "加强血糖监测，或先咨询医师。"},
    {"id": "renshen-anticoag", "herbs": ["人参"], "level": "warn",
     "triggers": {"medications": ["anticoagulant"]},
     "reason": "人参可能降低华法林等抗凝药效果。",
     "action": "先咨询医师并监测凝血指标。"},
    {"id": "huangqi-antidiabetic", "herbs": ["黄芪"], "level": "warn",
     "triggers": {"medications": ["antidiabetic", "antihypertensive"]},
     "reason": "黄芪有辅助降压、降糖作用，与西药叠加可能导致血压或血糖偏低。",
     "action": "加强监测。"},

    # ---- 黄连/黄芩 等 x 华法林 -------------------------------------------
    {"id": "huanglian-anticoag", "herbs": ["黄连", "黄芩", "黄柏", "大黄", "丹参"],
     "level": "warn",
     "triggers": {"medications": ["anticoagulant"]},
     "reason": "这类药材可能影响华法林的代谢，使 INR 波动。",
     "action": "先咨询医师并监测 INR。"},

    # ---- 泻下类 -----------------------------------------------------------
    {"id": "xiexia-laxative", "level": "warn",
     "herbs": ["大黄", "芒硝", "番泻叶", "郁李仁", "火麻仁"],
     "triggers": {"medications": ["antidiabetic"]},
     "reason": "泻下类药材与部分降糖药合用可能加剧腹泻与脱水。",
     "action": "观察排便情况，不适即停。"},
    {"id": "xiexia-ulcer", "level": "block",
     "herbs": ["大黄", "芒硝", "番泻叶", "甘遂", "大戟", "芫花", "商陆",
               "巴豆", "千金子"],
     "triggers": {"conditions": ["胃溃疡", "胃及十二指肠溃疡", "胃炎", "肠炎",
                                "溃疡性结肠炎"]},
     "reason": "峻下与刺激性泻下药材会直接刺激溃疡面。",
     "action": "换方。"},
    {"id": "xiexia-elderly", "level": "warn",
     "herbs": ["大黄", "芒硝", "番泻叶", "巴豆", "甘遂", "大戟", "芫花"],
     "triggers": {"special": ["老年"]},
     "reason": "老年人用峻下药易致脱水、电解质紊乱与跌倒。",
     "action": "不宜自行使用。"},

    # ---- 五味子 / 免疫抑制 ------------------------------------------------
    {"id": "wuweizi-immuno", "herbs": ["五味子"], "level": "block",
     "triggers": {"medications": ["immunosuppressant"]},
     "reason": "五味子可升高他克莫司、环孢素血药浓度。",
     "action": "换方，或由移植／风湿科医师调整剂量。"},

    # ---- 含钙 / 含碘 ------------------------------------------------------
    {"id": "calcium-antibiotic", "level": "warn",
     "herbs": ["石膏", "牡蛎", "龙骨", "珍珠母", "石决明", "瓦楞子",
               "海螵蛸", "钟乳石"],
     "triggers": {"medications": ["quinolone_tetracycline"]},
     "reason": "钙质会与四环素、喹诺酮类抗生素络合，降低吸收。",
     "action": "两类药间隔 2 小时以上服用。"},
    {"id": "iodine-thyroid", "level": "block",
     "herbs": ["海藻", "昆布", "海带"],
     "triggers": {"medications": ["thyroid"], "conditions": ["甲状腺机能亢进", "甲亢"]},
     "reason": "海藻昆布富含碘，会干扰甲状腺功能与抗甲亢治疗。",
     "action": "换方。"},

    # ---- 抗胆碱能 ---------------------------------------------------------
    {"id": "anticholinergic-herbs", "level": "block",
     "herbs": ["洋金花", "曼陀罗", "天仙子", "颠茄"],
     "triggers": {"medications": ["anticholinergic"],
                  "conditions": ["青光眼", "前列腺增生", "前列腺肥大"]},
     "reason": "这类药材含莨菪烷类生物碱，与抗胆碱药叠加或加重青光眼、排尿困难。",
     "action": "换方。"},

    # ---- 含酒辅料 ---------------------------------------------------------
    {"id": "alcohol-disulfiram", "level": "block",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"medications": ["nitroimidazole", "cephalosporin"]},
     "reason": "酒精与甲硝唑、部分头孢合用可引起双硫仑样反应（面红、心悸、呕吐、血压下降）。",
     "action": "换用不含酒的方，或停药 7 天后再用。"},
    {"id": "alcohol-antidiabetic", "level": "block",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"medications": ["antidiabetic"]},
     "reason": "酒精可诱发低血糖，并掩盖低血糖症状。",
     "action": "换方。"},
    {"id": "alcohol-psychotropic", "level": "block",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"medications": ["psychotropic", "maoi"]},
     "reason": "酒精与镇静、抗抑郁药叠加中枢抑制，可致呼吸抑制。",
     "action": "换方。"},
    {"id": "alcohol-statin", "level": "warn",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"medications": ["statin"]},
     "reason": "酒精与他汀合用增加肝损伤与肌病风险。",
     "action": "不宜同用。"},
    {"id": "alcohol-liver", "level": "block",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"conditions": ["肝病", "肝炎", "肝硬化", "脂肪肝", "肝功能异常"]},
     "reason": "酒精加重肝损伤。",
     "action": "换用不含酒的方。"},
    {"id": "alcohol-ulcer", "level": "warn",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"conditions": ["胃溃疡", "胃及十二指肠溃疡", "胃炎"]},
     "reason": "酒精刺激胃黏膜，加重溃疡与炎症。",
     "action": "换方。"},
    {"id": "alcohol-pregnancy", "level": "block",
     "herbs": ["黄酒", "白酒", "米酒", "酒"],
     "triggers": {"special": ["孕期", "备孕", "哺乳"]},
     "reason": "酒精在孕期、备孕期与哺乳期均应避免。",
     "action": "换方。"},

    # ---- 含糖辅料 ---------------------------------------------------------
    {"id": "sugar-diabetes", "level": "warn",
     "herbs": ["白糖", "红糖", "冰糖", "蜂蜜", "饴糖", "砂糖"],
     "triggers": {"conditions": ["糖尿病", "血糖高", "高血糖"],
                  "diet": ["限糖", "低糖", "控糖"]},
     "reason": "含糖辅料会直接影响血糖。",
     "action": "换用无糖配方的方，或在医师指导下调整。"},
    {"id": "honey-infant", "level": "block",
     "herbs": ["蜂蜜"],
     "triggers": {"special": ["婴幼儿", "婴儿", "新生儿"]},
     "reason": "1 岁以下婴儿禁用蜂蜜，存在肉毒杆菌中毒风险。",
     "action": "换方。"},

    # ---- 孕期 / 备孕 / 哺乳 -----------------------------------------------
    {"id": "pregnancy-huoxue", "level": "block",
     "herbs": ["丹参", "红花", "桃仁", "水蛭", "三棱", "莪术", "麝香",
               "益母草", "牛膝", "川芎", "赤芍", "虻虫", "地鳖虫",
               "王不留行", "穿山甲"],
     "triggers": {"special": ["孕期", "怀孕", "备孕"]},
     "reason": "活血化瘀与破血类药材在孕期有流产风险。",
     "action": "孕期不使用，请由产科或中医师评估。"},
    {"id": "pregnancy-xiexia", "level": "block",
     "herbs": ["大黄", "芒硝", "番泻叶", "巴豆", "甘遂", "大戟", "芫花",
               "商陆", "牵牛子"],
     "triggers": {"special": ["孕期", "怀孕", "备孕"]},
     "reason": "峻下逐水类药材可致流产。",
     "action": "孕期禁用。"},
    {"id": "pregnancy-aconite", "level": "block",
     "herbs": ["附子", "川乌", "草乌", "乌头", "半夏", "南星", "白附子"],
     "triggers": {"special": ["孕期", "怀孕", "备孕"]},
     "reason": "乌头类与半夏南星系妊娠禁忌药。",
     "action": "孕期禁用。"},
    {"id": "lactation-strong", "level": "block",
     "herbs": ["大黄", "番泻叶", "芒硝", "麦芽", "薄荷"],
     "triggers": {"special": ["哺乳", "哺乳期", "喂奶"]},
     "reason": "泻下类可经乳汁影响婴儿；麦芽、薄荷有回乳作用。",
     "action": "哺乳期避免，换方。"},
    {"id": "fertility-toxic", "level": "block",
     "herbs": ["雷公藤", "马兜铃", "关木通", "广防己", "棉酚"],
     "triggers": {"special": ["备孕", "孕期", "哺乳"], "conditions": ["不育"]},
     "reason": "这类药材有明确的生殖与肾毒性。",
     "action": "禁用。"},

    # ---- 肾病 / 马兜铃酸 --------------------------------------------------
    {"id": "aristolochic-kidney", "level": "block",
     "herbs": ["马兜铃", "关木通", "广防己", "青木香", "天仙藤", "细辛"],
     "triggers": {"conditions": ["肾病", "肾功能不全", "肾病综合征", "肾盂肾炎",
                                "尿毒症", "慢性肾炎"]},
     "reason": "含马兜铃酸类药材有明确肾毒性。",
     "action": "换方，肾病人群应避开。"},

    # ---- 蚕豆病 -----------------------------------------------------------
    {"id": "g6pd-fava", "level": "block",
     "herbs": ["蚕豆", "蚕豆花", "蚕豆叶", "薄荷", "金银花", "黄连", "珍珠粉"],
     "triggers": {"conditions": ["蚕豆病", "G6PD", "葡萄糖六磷酸脱氢酶缺乏"]},
     "reason": "蚕豆病（G6PD 缺乏）接触氧化性物质可诱发溶血。",
     "action": "换方，逐味核对原料。"},

    # ---- 其他 -------------------------------------------------------------
    {"id": "aconite-antiarrhythmic", "level": "block",
     "herbs": ["附子", "川乌", "草乌", "乌头"],
     "triggers": {"medications": ["digoxin", "antihypertensive"],
                  "conditions": ["心律失常"]},
     "reason": "乌头碱影响心脏传导，与心脏用药叠加风险高。",
     "action": "换方，须经医师评估。"},
    {"id": "sedative-mineral", "level": "warn",
     "herbs": ["朱砂", "磁石", "龙骨", "牡蛎"],
     "triggers": {"medications": ["psychotropic"]},
     "reason": "重镇安神类药材与镇静药叠加可能过度抑制。",
     "action": "观察嗜睡、乏力，不适即停。"},
    {"id": "salt-restriction", "level": "warn",
     "herbs": ["盐", "酱油", "咸菜", "腌"],
     "triggers": {"diet": ["限盐", "低盐", "低钠"], "conditions": ["高血压", "心力衰竭", "肾病综合征"]},
     "reason": "含盐调味与限钠要求冲突。",
     "action": "改用无盐或低钠调味，或换方。"},
]

VALID_LEVELS = ("block", "warn")

# ---------------------------------------------------------------------------
# Route detection.
#
# The book mixes oral and topical formulas in the same section, and several
# topical ones contain herbs that would be unacceptable by mouth — `麻黄外用
# 治疗风寒咳嗽` is a plaster on 肺俞穴, not a decoction. Treating both the same
# way is wrong in both directions: it blocks a safe topical remedy and it
# under-warns a systemic one.
#
# Topical formulas are not risk-free (transdermal absorption is real), so the
# hits are downgraded one level rather than dropped.
# ---------------------------------------------------------------------------
EXTERNAL_MARKERS = (
    "外敷", "外搽", "外洗", "外贴", "外涂", "外擦", "外用", "外熏",
    "贴敷", "敷于", "敷患处", "涂于", "搽患处", "洗患处", "熏洗",
    "坐浴", "含漱", "滴耳", "滴鼻", "塞鼻", "纳入", "吹入", "撒在",
    "贴于", "敷脐", "填脐", "药浴", "浸泡患处",
    # The scan mixes simplified and traditional glyphs for 贴/敷.
    "贴", "貼", "敷", "搽", "涂", "塗",
)
INTERNAL_MARKERS = ("内服", "口服", "煎服", "水煎服", "顿服", "送服", "冲服", "代茶饮")


def detect_route(usage_text: str) -> str:
    """Return "external", "internal" or "unknown" from the book's 制用法 text."""
    if not usage_text:
        return "unknown"
    external = sum(1 for m in EXTERNAL_MARKERS if m in usage_text)
    internal = sum(1 for m in INTERNAL_MARKERS if m in usage_text)
    if external and not internal:
        return "external"
    if internal and not external:
        return "internal"
    if external > internal:
        return "external"
    if internal > external:
        return "internal"
    return "unknown"


def _downgrade(level: str) -> str:
    return "warn" if level == "block" else level


# Longer herb names that must suppress a shorter rule match. `麻黄根` is a
# different herb from `麻黄` (止汗 vs 发汗) and must not inherit its rules.
# Herbs whose longer forms are the *same* herb (生甘草/炙甘草, 生附子/制附子)
# are deliberately absent — those should keep matching.
SHADOWING_NAMES: dict[str, list[str]] = {
    "麻黄": ["麻黄根", "麻黄绒"],
    "人参": ["人参叶", "人参须"],
    "三七": ["三七花"],
    "薄荷": ["薄荷脑"],
    "陈皮": ["陈皮丝"],
    "菊花": ["菊花脑"],
    "荷叶": ["荷叶蒂"],
    "竹叶": ["竹叶卷心"],
}


def _present(herb: str, text: str) -> bool:
    """True when the herb appears on its own, not merely inside a longer name.

    `麻黄` must not fire for `麻黄根`. Counting occurrences is enough: every
    occurrence of a shadowing name also counts as an occurrence of the shorter
    herb, so the herb is genuinely present only when the totals differ.
    """
    total = text.count(herb)
    if total == 0:
        return False
    shadows = SHADOWING_NAMES.get(herb)
    if not shadows:
        return True
    shadowed = sum(text.count(name) for name in shadows)
    return total > shadowed


def prepare_profile(profile: dict) -> dict:
    """Fill in the derived drug classes when the caller passed a raw dict.

    `load_profile()` already does this, but `evaluate()` is a public entry
    point and must behave the same whether the caller came through the
    storage layer or handed over an ad-hoc dictionary.
    """
    if not profile:
        return profile
    if profile.get("_drug_classes") is None:
        profile["_drug_classes"] = normalize_drugs(profile.get("medications") or [])
    if profile.get("_unknown_drugs") is None:
        profile["_unknown_drugs"] = unknown_drugs(profile.get("medications") or [])
    return profile


def evaluate(formula_text: str, profile: dict, *,
             usage_text: str | None = None) -> list[dict]:
    """Return the interaction hits for one formula against one profile.

    `formula_text` should be the formula's ingredients plus usage, so that
    alcohol used as a vehicle is caught even when it is only named in 制用法.
    `usage_text` is used to detect the route; pass it separately when
    `formula_text` has already been concatenated.
    """
    hits: list[dict] = []
    if not profile:
        return hits

    profile = prepare_profile(profile)
    route = detect_route(usage_text if usage_text is not None else formula_text)

    active = {
        "medications": list(profile.get("_drug_classes") or []),
        "conditions": [str(c) for c in profile.get("conditions") or []],
        "special": [str(s) for s in profile.get("special") or []],
        "diet": [str(d) for d in profile.get("diet") or []],
    }

    for rule in INTERACTION_RULES:
        matched_herbs = [h for h in rule["herbs"] if _present(h, formula_text)]
        if not matched_herbs:
            continue
        for trigger_kind, wanted in rule["triggers"].items():
            for value in wanted:
                pool = active.get(trigger_kind) or []
                if any(value in entry or entry in value for entry in pool):
                    level = rule["level"]
                    note = ""
                    if route == "external" and level == "block":
                        level = _downgrade(level)
                        note = ("本方在原书中是外用（敷、贴、洗、搽等），"
                                "全身吸收远低于口服，风险相应降低；"
                                "但仍建议先咨询药师或医师。")
                    hits.append({
                        "id": rule["id"],
                        "level": level,
                        "herbs": matched_herbs,
                        "trigger_kind": trigger_kind,
                        "trigger": value,
                        "route": route,
                        "reason": rule["reason"],
                        "action": rule["action"],
                        "note": note,
                    })
                    break
            else:
                continue
            break

    order = {"block": 0, "warn": 1}
    return sorted(hits, key=lambda h: order.get(h["level"], 2))


def worst_level(hits: list[dict]) -> str | None:
    if not hits:
        return None
    return hits[0]["level"]
