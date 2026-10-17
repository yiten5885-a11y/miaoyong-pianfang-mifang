#!/usr/bin/env python3
"""Deterministic retrieval over the packaged formula records.

Usage
-----
    python3 scripts/search.py --query "老是咳嗽有痰"
    python3 scripts/search.py --condition 咳嗽 --limit 5
    python3 scripts/search.py --list-conditions
    python3 scripts/search.py --stats

The script never calls a model. It returns the ranked source records so the
host assistant can shape the answer; it also returns the safety annotation so
the assistant does not have to re-derive it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = SKILL_ROOT / "assets" / "records.jsonl"

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from safety import scan_herbs, worst_level  # noqa: E402

STOP_GRAMS = {
    "什么", "哪些", "怎么", "如何", "是否", "有没有", "多少", "需要", "可以",
    "适合", "一下", "请问", "偏方", "秘方", "验方", "方子", "原书", "书上",
    "治疗", "治一下", "方法", "办法", "帮我", "我想", "最近", "一直",
}

# Colloquial phrasing -> canonical condition name in the book.
#
# Coverage rule: every condition with >=4 records must be reachable from at
# least one phrase a real person would type. Several book headings are archaic
# (乌须美发, 肤生赘物, 赤鼻白瘢) and would never be spoken, so each gets an
# explicit modern gloss.
#
# Longest phrase wins at match time, so "月经提前" beats "月经".
SYNONYMS: dict[str, str] = {
    # ---- 第一章 内科 ------------------------------------------------------
    "感冒": "感冒", "受凉": "感冒", "伤风": "感冒", "着凉": "感冒",
    "风吹着了": "感冒", "鼻塞": "感冒", "打喷嚏": "感冒",
    "咳嗽": "咳嗽", "咳痰": "咳嗽", "干咳": "咳嗽", "老咳": "咳嗽",
    "嗓子痒想咳": "咳嗽", "咳嗽有痰": "咳嗽",
    "百日咳": "百日咳", "顿咳": "百日咳", "鸡咳": "百日咳",
    "哮喘": "哮喘", "气喘": "哮喘", "喘不上气": "哮喘", "吼喘": "哮喘",
    "支气管哮喘": "支气管哮喘",
    "气管炎": "支气管炎", "支气管炎": "支气管炎", "老慢支": "支气管炎",
    "支气管扩张": "支气管扩张", "支扩": "支气管扩张",
    "肺脓肿": "肺脓肿", "肺结核": "肺结核", "痨病": "肺结核", "肺炎": "肺炎",
    "胃炎": "胃炎", "慢性胃炎": "慢性胃炎", "浅表性胃炎": "慢性胃炎",
    "胃痛": "胃痛", "胃疼": "胃痛", "胃脘痛": "胃脘痛", "心口痛": "胃脘痛",
    "胃溃疡": "胃及十二指肠溃疡", "十二指肠溃疡": "胃及十二指肠溃疡",
    "胃下垂": "胃下垂",
    "打嗝": "呃逆", "呃逆": "呃逆", "嗝逆": "呃逆",
    "呕吐": "呕吐", "想吐": "呕吐", "恶心呕吐": "呕吐",
    "拉肚子": "腹泻", "腹泻": "腹泻", "拉稀": "腹泻", "闹肚子": "腹泻",
    "急慢性腹泻": "急慢性腹泻", "经常拉肚子": "急慢性腹泻",
    "急性肠胃炎": "急性胃肠炎", "上吐下泻": "急性胃肠炎",
    "痢疾": "痢疾", "拉痢": "痢疾",
    "便秘": "便秘", "排便困难": "便秘", "大便干": "便秘", "大便干结": "便秘",
    "拉不出来": "便秘", "没上厕所": "便秘", "几天没拉": "便秘",
    "排便费力": "便秘", "蹲不出来": "便秘",
    "便血": "便血", "大便带血": "便血", "痔血": "便血",
    "消化不良": "消化不良", "不消化": "消化不良", "胃胀": "消化不良",
    "吃不下": "消化不良", "没胃口": "消化不良", "食欲不振": "消化不良",
    "肠梗阻": "肠梗阻", "肚子胀不排气": "肠梗阻",
    "腹痛": "腹痛", "肚子疼": "腹痛", "肚子痛": "腹痛", "腹疼": "腹痛",
    "胆囊炎": "胆囊炎", "胆石症": "胆石症", "胆结石": "胆石症",
    "黄疸": "黄疸", "身黄": "黄疸", "眼黄": "黄疸",
    "肝炎": "肝炎", "肝脾肿大": "肝炎、肝脾肿大", "肝大": "肝炎、肝脾肿大",
    "肝硬化": "肝硬化", "肝腹水": "浮肿、腹水", "腹水": "浮肿、腹水",
    "浮肿": "浮肿、腹水", "水肿": "浮肿、腹水",
    "脂肪肝": "脂肪肝",
    "心律不齐": "心律失常", "心律失常": "心律失常",
    "心悸": "心悸", "心慌": "心悸", "心跳": "心悸",
    "心绞痛": "心绞痛", "胸口疼": "心绞痛",
    "心力衰竭": "心力衰竭", "心衰": "心力衰竭",
    "心动过速": "心动过速", "心跳快": "心动过速", "心跳过快": "心动过速",
    "冠心病": "冠心病", "动脉硬化": "动脉硬化", "动脉粥样硬化": "动脉硬化",
    "风湿性心脏病": "风湿性心脏病", "风心病": "风湿性心脏病",
    "肺原性心脏病": "肺原性心脏病", "肺心病": "肺原性心脏病",
    "心肌炎": "病毒性心肌炎", "病毒性心肌炎": "病毒性心肌炎",
    "高血压": "高血压", "血压高": "高血压", "血压有点高": "高血压",
    "低血压": "低血压", "血压低": "低血压",
    "血脂高": "高血脂症", "高血脂": "高血脂症", "血稠": "高血脂症",
    "贫血": "贫血", "缺铁性贫血": "缺铁性贫血", "缺铁贫血": "缺铁性贫血",
    "再生障碍性贫血": "再生障碍性贫血", "再障": "再生障碍性贫血",
    "坏血病": "坏血病", "白血病": "白血病",
    "紫癜": "紫癜", "血小板减少": "血小板减少症", "血小板低": "血小板减少症",
    "白细胞减少": "白细胞减少症", "白细胞低": "白细胞减少症",
    "中风": "脑中风", "脑中风": "脑中风", "偏瘫": "脑中风", "脑梗塞": "脑中风",
    "尿道炎": "尿道炎", "膀胱炎": "膀胱炎",
    "尿路结石": "尿路结石", "肾结石": "尿路结石", "输尿管结石": "尿路结石",
    "结石": "结石症", "尿血": "尿血", "血尿": "尿血",
    "乳糜尿": "乳糜尿", "尿白": "乳糜尿",
    "遗尿": "遗尿", "尿床": "遗尿",
    "尿潴留": "尿潴留", "尿不出": "尿潴留", "小便不利": "小便不利",
    "小便不通": "小便不通", "排尿困难": "小便不通",
    "肾盂肾炎": "肾盂肾炎", "肾结核": "肾结核", "尿毒症": "尿毒症",
    "肾病": "肾病综合征", "肾病综合征": "肾病综合征", "蛋白尿": "肾病综合征",
    "癫痫": "癫痫", "羊角风": "癫痫", "羊癫疯": "癫痫",
    "癔病": "癔病", "歇斯底里": "癔病",
    "神经衰弱": "神经衰弱", "失眠": "神经衰弱", "睡不着": "神经衰弱",
    "入睡困难": "神经衰弱", "睡不好": "神经衰弱", "翻来覆去": "神经衰弱",
    "多梦": "神经衰弱", "睡眠差": "神经衰弱",
    "精神分裂": "精神分裂症", "精神分裂症": "精神分裂症",
    "抑郁": "抑郁性神经症", "抑郁症": "抑郁性神经症",
    "脑炎": "脑炎、脑膜炎", "脑膜炎": "脑炎、脑膜炎",
    "头痛": "头痛", "偏头痛": "头痛", "头疼": "头痛",
    "坐骨神经痛": "坐骨神经痛", "三叉神经痛": "三叉神经痛",
    "面瘫": "面神经炎", "面神经炎": "面神经炎", "面神经麻痹": "面神经炎",
    "神经性皮炎": "神经性皮炎",
    "多发性神经炎": "多发性神经炎", "末梢神经炎": "多发性神经炎",
    "心神经官能症": "心神经官能症", "心脏神经官能症": "心神经官能症",
    "胃肠神经官能症": "胃肠神经官能症",
    "性神经官能症": "性神经官能症",
    "糖尿病": "糖尿病", "血糖高": "糖尿病", "消渴": "糖尿病",
    "肥胖": "肥胖症", "减肥": "肥胖症", "减不下来": "肥胖症",
    "甲状腺": "甲状腺肿大", "甲状腺肿大": "甲状腺肿大", "大脖子": "甲状腺肿大",
    "瘿瘤": "甲状腺肿大(瘿瘤)", "甲状腺肿大(瘿瘤)": "甲状腺肿大(瘿瘤)",
    "甲状腺炎": "甲状腺炎",
    "甲亢": "甲状腺机能亢进症", "甲状腺机能亢进": "甲状腺机能亢进症",
    "甲减": "甲状腺机能减退症", "甲状腺机能减退": "甲状腺机能减退症",
    "霍乱": "霍乱", "佝偻病": "佝偻病", "缺钙": "佝偻病",

    # ---- 第二章 外科 ------------------------------------------------------
    "腮腺炎": "流行性腮腺炎、扁桃体炎", "痄腮": "流行性腮腺炎、扁桃体炎",
    "扁桃体炎": "流行性腮腺炎、扁桃体炎", "扁桃体发炎": "扁桃体炎",
    "淋巴结炎": "淋巴结核、慢性淋巴结炎", "淋巴结核": "淋巴结核、慢性淋巴结炎",
    "疝气": "疝气", "小肠气": "疝气",
    "阑尾炎": "阑尾炎", "盲肠炎": "阑尾炎",
    "脉管炎": "脉管炎", "静脉炎": "脉管炎",
    "丹毒": "丹毒",
    "疖子": "痈、疽、疔、疖", "长疖": "痈、疽、疔、疖", "痈": "痈、疽、疔、疖",
    "疔疮": "痈、疽、疔、疖", "无名肿毒": "痈、疽、疔、疖",
    "皮肤化脓": "痈、疽、疔、疖", "红肿热痛": "痈、疽、疔、疖",
    "烫伤": "水火烫伤", "烧伤": "水火烫伤", "被开水烫": "水火烫伤",
    "褥疮": "褥疮", "压疮": "褥疮",
    "蛇咬": "蛇咬伤", "被蛇咬": "蛇咬伤",
    "虫咬": "虫类咬伤", "蚊虫叮咬": "虫类咬伤", "蜂蜇": "虫类咬伤",
    "破伤风": "破伤风", "脑震荡": "脑震荡", "撞到头": "脑震荡",
    "乳腺炎": "乳腺炎(乳痛)", "乳痛": "乳腺炎(乳痛)", "乳房胀痛": "乳腺炎(乳痛)",
    "乳腺增生": "乳腺炎(乳痛)",
    "痔疮": "痔疮", "痔": "痔疮", "长痔疮": "痔疮",
    "肛裂": "肛门裂", "肛门裂": "肛门裂",
    "鸡眼": "鸡眼", "跌打损伤": "跌打损伤", "扭伤": "跌打损伤",
    "刀划": "跌打损伤", "割伤": "跌打损伤", "划伤": "跌打损伤",
    "划破": "跌打损伤", "刀子划": "跌打损伤", "破了口子": "跌打损伤",
    "伤口": "跌打损伤", "出血": "跌打损伤",
    "淤青": "跌打损伤", "摔伤": "跌打损伤", "崴脚": "跌打损伤",
    "骨结核": "骨结核", "骨髓炎": "骨髓炎",

    # ---- 第三章 男科病 ----------------------------------------------------
    "阳痿": "阳痿", "硬不起来": "阳痿", "不行": "阳痿", "勃起": "阳痿",
    "早泄": "早泄", "时间短": "早泄", "一触即泄": "早泄",
    "性欲低下": "性欲低下", "没性欲": "性欲低下", "性欲低": "性欲低下",
    "遗精": "遗精", "滑精": "遗精",
    "阳缩": "阳缩、阳强", "阳强": "阳缩、阳强",
    "不射精": "不射精症", "不射精症": "不射精症",
    "逆行射精": "逆行射精", "射精疼痛": "射精疼痛", "射精疼": "射精疼痛",
    "无精": "无精子症", "无精子症": "无精子症",
    "少精": "少精子症", "少精子症": "少精子症",
    "死精": "死精子症", "死精子症": "死精子症",
    "精液不液化": "精液不液化",
    "前列腺炎": "前列腺炎", "前列腺增生": "前列腺增生症",
    "前列腺肥大": "前列腺增生症",
    "睾丸炎": "睾丸炎", "蛋疼": "睾丸炎",
    "阴囊肿": "阴囊、阴茎肿痛", "阴囊、阴茎肿痛": "阴囊、阴茎肿痛",
    "男性更年期": "男性更年期综合症",
    "男性更年期综合症": "男性更年期综合症",

    # ---- 第四章 妇科病 ----------------------------------------------------
    "月经不调": "月经先后不定期", "月经先后不定期": "月经先后不定期",
    "月经提前": "月经先期", "月经先期": "月经先期",
    "月经推后": "月经后期", "月经推迟": "月经后期", "月经后期": "月经后期",
    "经期延长": "经期延长", "经期长": "经期延长",
    "月经量多": "月经量多", "月经多": "月经量多", "量多": "月经量多",
    "月经量少": "月经量少", "月经少": "月经量少", "量少": "月经量少",
    "痛经": "痛经", "来月经疼": "痛经", "月经疼": "痛经",
    "月经来的时候疼": "痛经", "月经来疼": "痛经", "经期疼": "痛经",
    "来例假疼": "痛经", "例假疼": "痛经", "痛经疼": "痛经",
    "闭经": "闭经", "停经": "闭经", "不来月经": "闭经",
    "倒经": "倒经", "经期流鼻血": "倒经",
    "崩漏": "崩漏", "血崩": "崩漏",
    "子宫出血": "子宫出血", "阴道出血": "子宫出血",
    "子宫颈糜烂": "子宫颈糜烂", "宫颈糜烂": "子宫颈糜烂",
    "子宫脱垂": "子宫脱垂", "阴挺": "子宫脱垂",
    "子宫内膜异位": "子宫内膜异位症", "子宫内膜异位症": "子宫内膜异位症",
    "子宫肌瘤": "子宫肌瘤", "阴道炎": "阴道炎", "盆腔炎": "盆腔炎",
    "带下": "带下", "白带多": "带下", "白带异常": "带下",
    "妊娠呕吐": "妊娠呕吐", "孕吐": "妊娠呕吐",
    "妊娠高血压": "妊娠高血压",
    "流产": "先兆流产", "先兆流产": "先兆流产", "见红": "先兆流产",
    "习惯性流产": "习惯性流产", "保胎": "习惯性流产",
    "产后恶露": "产后恶漏不尽", "恶露不尽": "产后恶漏不尽",
    "产后恶漏不尽": "产后恶漏不尽",
    "产后缺乳": "产后缺乳", "奶水少": "产后缺乳",
    "回乳": "回乳", "断奶": "回乳",
    "产后体虚": "产后体虚", "产后虚": "产后体虚",
    "产后腰痛": "产后腰痛", "产后腰疼": "产后腰痛",
    "产后便秘": "产后便秘",
    "乳头疾患": "乳头疾患", "乳头皲裂": "乳头疾患", "乳头疼痛": "乳头疾患",
    "更年期": "更年期综合症", "更年期综合症": "更年期综合症",

    # ---- 第五章 小儿科疾病 ------------------------------------------------
    "小儿发热": "小儿发热", "孩子发烧": "小儿发热",
    "小孩发烧": "小儿发热", "宝宝发烧": "小儿发热", "婴儿发烧": "小儿发热",
    "小儿感冒": "小儿感冒", "孩子感冒": "小儿感冒",
    "小孩感冒": "小儿感冒", "宝宝感冒": "小儿感冒",
    "小儿惊风": "小儿惊风", "孩子抽搐": "小儿惊风",
    "孩子受惊": "小儿惊风", "小孩受惊": "小儿惊风", "宝宝受惊": "小儿惊风",
    "小儿咳喘": "小儿咳喘", "孩子咳嗽喘": "小儿咳喘",
    "孩子咳嗽": "小儿咳喘", "小孩咳嗽": "小儿咳喘",
    "宝宝咳嗽": "小儿咳喘", "婴儿咳嗽": "小儿咳喘",
    "小儿泄泻": "小儿泄泻", "孩子拉肚子": "小儿泄泻",
    "小孩拉肚子": "小儿泄泻", "宝宝拉肚子": "小儿泄泻",
    "婴儿拉肚子": "小儿泄泻", "孩子腹泻": "小儿泄泻",
    "小儿痢疾": "小儿痢疾", "孩子痢疾": "小儿痢疾",
    "小儿脱肛": "小儿脱肛", "孩子脱肛": "小儿脱肛",
    "小儿遗尿": "小儿遗尿", "孩子尿床": "小儿遗尿",
    "小孩尿床": "小儿遗尿", "宝宝尿床": "小儿遗尿",
    "小儿流涎": "小儿流涎", "孩子流口水": "小儿流涎",
    "小儿夜啼": "小儿夜啼", "孩子夜哭": "小儿夜啼", "小孩夜哭": "小儿夜啼", "孩子夜里哭": "小儿夜啼",
    "孩子半夜哭": "小儿夜啼", "小孩半夜哭": "小儿夜啼",
    "半夜哭闹": "小儿夜啼", "孩子哭闹": "小儿夜啼", "夜里哭闹": "小儿夜啼",
    "小儿厌食": "小儿厌食和异食癖", "孩子不吃饭": "小儿厌食和异食癖",
    "积食": "小儿厌食和异食癖", "小儿积食": "小儿厌食和异食癖",
    "小儿呕吐": "小儿呕吐和吐乳", "孩子吐奶": "小儿呕吐和吐乳",
    "小儿多动症": "小儿多动症", "孩子多动": "小儿多动症",
    "小儿汗证": "小儿汗证", "孩子出虚汗": "小儿汗证",
    "小儿疳积": "小儿疳积", "孩子疳积": "小儿疳积",
    "胎毒疹痘": "胎毒疹痘", "婴儿起疹": "胎毒疹痘", "新生儿疹子": "胎毒疹痘",

    # ---- 第六章 五官科 ----------------------------------------------------
    "麦粒肿": "麦粒肿", "针眼": "麦粒肿",
    "睑缘炎": "睑缘炎", "烂眼边": "睑缘炎",
    "泪囊炎": "泪囊炎", "结膜炎": "结膜炎", "红眼病": "结膜炎",
    "翼状胬肉": "翼状胬肉", "夜盲症": "夜盲症", "夜盲": "夜盲症",
    "白内障": "白内障", "电光性眼炎": "电光性眼炎", "电焊刺眼": "电光性眼炎",
    "中耳炎": "中耳炎", "耳朵流脓": "中耳炎",
    "耳鸣": "耳鸣、耳聋", "耳聋": "耳鸣、耳聋", "耳鸣、耳聋": "耳鸣、耳聋",
    "昆虫人耳": "昆虫人耳", "虫子进耳朵": "昆虫人耳",
    "美尼尔": "内耳眩晕症(美尼尔氏综合征)", "眩晕": "内耳眩晕症(美尼尔氏综合征)",
    "头晕目眩": "内耳眩晕症(美尼尔氏综合征)",
    "内耳眩晕症": "内耳眩晕症(美尼尔氏综合征)",
    "鼻出血": "鼻出血", "流鼻血": "鼻出血",
    "鼻窦炎": "鼻窦炎", "鼻息肉": "臭鼻症和鼻息肉",
    "臭鼻症和鼻息肉": "臭鼻症和鼻息肉",
    "咽喉肿痛": "急性咽喉炎、咽喉肿痛", "嗓子疼": "急性咽喉炎、咽喉肿痛",
    "喉咙痛": "急性咽喉炎、咽喉肿痛", "咽炎": "慢性咽炎",
    "慢性咽炎": "慢性咽炎", "急性喉炎": "急性喉炎",
    "慢性喉炎": "慢性喉炎", "误吞": "误吞(刺)硬物",
    "卡鱼刺": "误吞(刺)硬物", "鱼刺卡喉": "误吞(刺)硬物",
    "失音": "失音", "嗓子哑": "失音", "说不出话": "失音",
    "口腔溃疡": "口腔溃疡", "口疮": "口腔溃疡", "嘴里溃疡": "口腔溃疡",
    "口臭": "口臭", "口气": "口臭",
    "牙痛": "牙痛", "牙疼": "牙痛", "牙龈炎": "牙龈炎",
    "牙龈出血": "牙龈炎", "牙周炎": "牙周炎",

    # ---- 第七章 皮肤科 ----------------------------------------------------
    "黄褐斑": "黄褐斑", "色斑": "黄褐斑", "雀斑": "雀斑",
    "粉刺": "粉刺", "痘痘": "粉刺", "青春痘": "粉刺", "痤疮": "粉刺",
    "痱子": "痱子", "皮炎": "皮炎", "皮肤发炎": "皮炎",
    "湿疹": "湿疹", "荨麻疹": "荨麻疹", "风疹块": "荨麻疹",
    "带状疱疹": "带状疱疹", "缠腰龙": "带状疱疹",
    "扁平疣": "扁平疣", "瘊子": "扁平疣",
    "头癣": "头癣", "手足癣": "手足癣", "手癣": "手足癣", "足癣": "手足癣",
    "牛皮癣": "牛皮癣", "银屑病": "牛皮癣",
    "酒糟鼻": "酒糟鼻", "酒槽鼻": "酒糟鼻", "红鼻子": "酒糟鼻",
    "灰指甲": "灰指甲", "脚气": "脚气",
    "小腿溃疡": "小腿溃疡(臁疮)", "臁疮": "小腿溃疡(臁疮)",
    "老烂腿": "小腿溃疡(臁疮)",
    "黄水疮": "黄水疮", "脓疱疮": "黄水疮",
    "疥疮": "疥疮", "毛囊炎": "毛囊炎",
    "皮肤瘙痒": "神经性皮炎", "身上痒": "神经性皮炎", "皮肤痒": "神经性皮炎",

    # ---- 第八章 美容 ------------------------------------------------------
    "乌须美发": "乌须美发", "白发": "乌须美发", "白头发": "乌须美发",
    "须发早白": "乌须美发", "想黑发": "乌须美发", "头发早白": "乌须美发",
    "肤生赘物": "肤生赘物", "皮肤长疙瘩": "肤生赘物",
    "皮肤小肉粒": "肤生赘物", "皮肤长东西": "肤生赘物",
    "美泽容颜": "美泽容颜", "脸色差": "美泽容颜", "面色不好": "美泽容颜",
    "减肥轻身": "减肥轻身", "瘦身": "减肥轻身", "轻身": "减肥轻身",
    "祛斑洁面": "祛斑洁面", "祛斑": "祛斑洁面", "去斑": "祛斑洁面",
    "赤鼻白瘢": "赤鼻白瘢", "鼻子红": "赤鼻白瘢", "白斑": "赤鼻白瘢",
    "腋下狐臭": "腋下狐臭", "狐臭": "腋下狐臭", "腋臭": "腋下狐臭",
    "腋下出汗": "腋下狐臭", "腋下味道": "腋下狐臭",
    "出汗有味道": "腋下狐臭", "腋窝有味": "腋下狐臭", "腋下有味": "腋下狐臭",
    "爽口香身": "爽口香身", "身上有味道": "爽口香身",
    "脱发": "乌须美发", "掉头发": "乌须美发", "头发掉": "乌须美发",
    "掉发": "乌须美发", "头发稀少": "乌须美发",
}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u3400" <= ch <= "\u9fff")


def grams(text: str, sizes=(2, 3, 4)) -> set[str]:
    normalized = normalize(text)
    result: set[str] = set()
    for size in sizes:
        for index in range(max(0, len(normalized) - size + 1)):
            gram = normalized[index:index + size]
            if gram not in STOP_GRAMS:
                result.add(gram)
    return result


def load_records(path: Path = DEFAULT_RECORDS) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(
            f"资料库未安装：{path}。请先接入拥有使用许可的 records.jsonl；"
            "不要用未获授权的 PDF、页图或转录替代。"
        )
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{number}: {exc}") from exc
    return records


def field_text(record: dict, field: str) -> str:
    return record.get(field) or ""


def searchable(record: dict) -> str:
    parts = [
        field_text(record, "condition"),
        field_text(record, "title"),
        field_text(record, "name"),
        field_text(record, "ingredients"),
        field_text(record, "usage"),
        field_text(record, "effect"),
    ]
    return normalize(" ".join(parts))


def score(record: dict, query: str, query_grams: set[str]) -> float:
    condition = normalize(field_text(record, "condition"))
    title = normalize(field_text(record, "title"))
    name = normalize(field_text(record, "name"))
    effect = normalize(field_text(record, "effect"))
    body = searchable(record)

    value = 0.0
    normalized_query = normalize(query)
    if condition and condition == normalized_query:
        value += 60.0
    elif condition and condition in normalized_query:
        value += 45.0
    elif normalized_query and normalized_query in condition:
        value += 30.0
    if name and name == normalized_query:
        value += 25.0
    elif name and (name in normalized_query or normalized_query in name):
        value += 12.0
    if title and normalized_query and normalized_query in title:
        value += 10.0
    if effect and normalized_query and normalized_query in effect:
        value += 8.0

    body_grams = grams(body)
    overlap = query_grams & body_grams
    value += len(overlap) * 0.6
    return value


def fuzzy_contains(phrase: str, text: str) -> float:
    """How strongly `phrase` appears in `text`, tolerating inserted words.

    Exact substring gives 1.0. Otherwise the phrase's characters must appear in
    order with limited slack — "嘴里溃疡" still matches "嘴里老是溃疡" because
    only two filler characters intervene, while "月经疼" does not match
    "月经来的时候疼得厉害" because the gap is too wide to be confident.

    Returns 0.0 when the phrase is absent or too scattered to be trustworthy.
    """
    if not phrase:
        return 0.0
    if phrase in text:
        return 1.0
    n = len(phrase)
    if n < 3:
        return 0.0

    position = -1
    gap_total = 0
    for char in phrase:
        index = text.find(char, position + 1)
        if index < 0:
            return 0.0
        if position >= 0:
            gap_total += index - position - 1
        position = index
        if gap_total > n:
            return 0.0
    return n / (n + gap_total)


# Words that put a query in a paediatric context. The book keeps 小儿* sections
# separate from their adult counterparts (小儿夜啼 vs 神经衰弱, 小儿泄泻 vs
# 腹泻), and without this bias "孩子半夜老是哭闹睡不好" resolves to adult
# insomnia. The marker only re-weights conditions the book itself prefixes with
# 小儿 — it never invents a paediatric reading of an adult section.
CHILD_MARKERS = (
    "孩子", "小孩", "宝宝", "婴儿", "儿童", "幼儿", "闺女", "儿子",
    "女儿", "小朋友", "新生儿", "娃",
)


def resolve_conditions(query: str, conditions: list[str]) -> list[str]:
    """Map a colloquial query onto book condition names.

    Scored rather than first-match-wins: a query can touch several conditions
    ("孩子半夜老是哭闹睡不好" is about a child, not about adult insomnia), so
    each candidate accumulates evidence and the strongest ones win.
    """
    normalized_query = normalize(query)
    available = set(conditions)
    is_child_context = any(marker in query for marker in CHILD_MARKERS)
    scores: dict[str, float] = {}

    for phrase, condition in SYNONYMS.items():
        if condition not in available:
            continue
        strength = fuzzy_contains(normalize(phrase), normalized_query)
        if strength <= 0:
            continue
        # Longer phrases are more specific and should dominate shorter ones.
        weight = (len(phrase) ** 1.5) * strength
        if is_child_context and condition.startswith("小儿"):
            weight *= 2.0
        if weight > scores.get(condition, 0.0):
            scores[condition] = weight

    for condition in conditions:
        normalized_condition = normalize(condition)
        if normalized_condition and normalized_condition in normalized_query:
            weight = (len(condition) ** 1.5) * 1.0
            if is_child_context and condition.startswith("小儿"):
                weight *= 2.0
            if weight > scores.get(condition, 0.0):
                scores[condition] = weight

    if not scores:
        return []
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best = ranked[0][1]
    # Keep only near-best candidates so a weak incidental hit cannot widen the
    # result set into unrelated sections.
    return [condition for condition, value in ranked if value >= best * 0.8]


# Explicit "and also" connectors. Punctuation is deliberately NOT a splitter:
# "最近老咳嗽，痰多" describes one symptom, while "感冒还嗓子疼" names two.
# The trailing + lets stacked connectors ("另外还有") count as one split.
MULTI_CONNECTOR_RE = re.compile(
    r"(?:(?:还有|再有|还|又|同时|并且|而且|加上|外加|以及|另外|"
    r"伴有|伴随))+"
)


def split_symptoms(query: str) -> list[str]:
    """Split a query into symptom segments when it explicitly names several.

    Returns a single-element list for ordinary one-symptom queries, so callers
    can treat both cases uniformly.
    """
    parts = [part.strip() for part in MULTI_CONNECTOR_RE.split(query)
             if part.strip()]
    return [part for part in parts if len(part) >= 2] or [query]


def resolve_conditions_multi(query: str, conditions: list[str]) -> list[str]:
    """Resolve a possibly multi-symptom query onto several conditions.

    The single-query scorer keeps only near-best candidates (`best * 0.8`),
    which is right for one symptom but silently drops the second one in
    "感冒还嗓子疼" — the phrase-length weight makes 感冒 (2 chars) lose to
    嗓子疼 (3 chars). Here each named symptom is resolved on its own and the
    results merged, so a user who reports two problems gets both sections.

    Ordinary queries keep the exact single-symptom behaviour: with no
    connector the "split" is the whole string and nothing changes.
    """
    segments = split_symptoms(query)
    if len(segments) <= 1:
        return resolve_conditions(query, conditions)

    hits: list[str] = []
    for segment in segments:
        for condition in resolve_conditions(segment, conditions):
            if condition not in hits:
                hits.append(condition)
    # Fall back to whole-query scoring when no segment resolved: the split may
    # have cut a phrase that only makes sense together.
    if not hits:
        return resolve_conditions(query, conditions)
    return hits


def annotate(record: dict) -> dict:
    herbs = scan_herbs(f"{record.get('ingredients', '')} {record.get('usage', '')}")
    return {
        "id": record.get("id"),
        "chapter": record.get("chapter"),
        "condition": record.get("condition"),
        "condition_no": record.get("condition_no"),
        "formula_no": record.get("formula_no"),
        "title": record.get("title"),
        "name": record.get("name"),
        "ingredients": record.get("ingredients"),
        "usage": record.get("usage"),
        "effect": record.get("effect"),
        "effect_label": record.get("effect_label"),
        "extra": record.get("extra", []),
        "pdf_page": record.get("pdf_page"),
        "book_page": record.get("book_page"),
        "source_refs": record.get("source_refs", []),
        "risk_herbs": herbs,
        "risk_level": worst_level(herbs),
    }


def suggest_conditions(query: str, records: list[dict], limit: int = 3) -> list[dict]:
    """Rank conditions the user might have meant, when nothing matched exactly.

    These are **suggestions for the user to pick from**, never an answer. The
    distinction matters: before v1.2 the searcher silently returned whatever
    scored highest, so "三天没上厕所了" produced a formula for oedema. Showing
    three candidate topics and asking is the honest failure mode.
    """
    query_grams = grams(query)
    if not query_grams:
        return []

    by_condition: dict[str, list[dict]] = {}
    for record in records:
        by_condition.setdefault(record.get("condition") or "", []).append(record)

    scored: list[tuple[float, str]] = []
    for condition, items in by_condition.items():
        name_grams = grams(condition)
        name_overlap = len(query_grams & name_grams)
        # Formula titles and effects are the book's own description of what the
        # section covers, so they are a fair proxy for topical relevance.
        body_grams = grams(" ".join(
            (item.get("title") or "") + (item.get("effect") or "")
            for item in items[:12]
        ))
        body_overlap = len(query_grams & body_grams)
        if name_overlap == 0 and body_overlap < 3:
            # An incidental single-gram hit in one formula's prose is noise —
            # it is how "眼睛干涩看不清" used to be answered with 闭经.
            continue
        value = name_overlap * 3.0 + body_overlap * 0.5
        if value > 0:
            scored.append((value, condition))

    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        return []
    best = scored[0][0]
    return [
        {"condition": condition, "score": round(value, 1)}
        for value, condition in scored[:limit] if value >= best * 0.5
    ]


def run_search(query: str, records: list[dict], limit: int = 5,
               chapter: str | None = None,
               condition: str | None = None) -> dict:
    conditions = sorted({r.get("condition", "") for r in records if r.get("condition")})
    matched_conditions = ([condition] if condition
                          else resolve_conditions_multi(query, conditions))

    pool = records
    if chapter:
        pool = [r for r in pool if chapter in (r.get("chapter") or "")]
    if matched_conditions:
        narrowed = [r for r in pool if r.get("condition") in matched_conditions]
        if narrowed:
            pool = narrowed

    query_grams = grams(query)
    ranked = sorted(
        ((score(r, query, query_grams), r) for r in pool),
        key=lambda item: (-item[0], item[1].get("pdf_page") or 0,
                          item[1].get("formula_no") or 0),
    )

    if matched_conditions:
        results = [annotate(r) for s, r in ranked[:limit] if s > 0]
        if not results:
            results = [annotate(r) for _, r in ranked[:limit]]
        return {
            "query": query,
            "matched_conditions": matched_conditions,
            "suggestions": [],
            "available_conditions": [],
            "results": results,
        }

    # No condition matched. Returning the top-ranked records here — which is
    # what this function used to do — produces a confident answer to a
    # question the user did not ask. Offer candidates instead.
    return {
        "query": query,
        "matched_conditions": [],
        "suggestions": suggest_conditions(query, records),
        "available_conditions": conditions,
        "results": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--condition", default=None)
    parser.add_argument("--chapter", default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--records", default=str(DEFAULT_RECORDS))
    parser.add_argument("--list-conditions", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    records = load_records(Path(args.records))

    if args.stats:
        conditions = {r.get("condition") for r in records}
        chapters = {r.get("chapter") for r in records}
        print(json.dumps({
            "records": len(records),
            "chapters": len(chapters),
            "conditions": len(conditions),
            "risky_records": sum(
                1 for r in records if scan_herbs(r.get("ingredients", "") or "")
            ),
        }, ensure_ascii=False, indent=2))
        return

    if args.list_conditions:
        grouped: dict[str, list[str]] = {}
        for record in records:
            grouped.setdefault(record.get("chapter") or "未归类", [])
            condition = record.get("condition") or "未归类"
            if condition not in grouped[record.get("chapter") or "未归类"]:
                grouped[record.get("chapter") or "未归类"].append(condition)
        print(json.dumps(grouped, ensure_ascii=False, indent=2))
        return

    if not args.query and not args.condition:
        parser.error("需要 --query 或 --condition")

    payload = run_search(args.query, records, args.limit, args.chapter, args.condition)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
