"""User-facing renderers for readonly major comparison tool states."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.data.major_data import associate_major_mappings, bachelor_major_mappings

if TYPE_CHECKING:
    from app.agent.context import RequestContext, ScoreDetail
    from app.schemas.user_profile import UserProfile


def is_missing_weight_major_compare_result(result_text: str) -> bool:
    return "暂时没有拿到当前会话可用的个性化量化权重数据" in str(result_text or "")


def _latest_user_text(request_context: RequestContext) -> str:
    for item in reversed(request_context.chat_history or []):
        if str(item.get("role") or "") == "user":
            return str(item.get("content") or "").strip()
    return ""


_PROVINCE_NAMES = (
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏",
    "新疆",
)
_SUBJECT_NAMES = ("物理", "历史", "化学", "生物", "政治", "地理")
_SUBJECT_ABBREVIATIONS = {
    "物": "物理",
    "史": "历史",
    "化": "化学",
    "生": "生物",
    "政": "政治",
    "地": "地理",
}


def _recent_user_text(request_context: RequestContext, *, max_turns: int = 4) -> str:
    texts: list[str] = []
    for item in reversed(request_context.chat_history or []):
        if str(item.get("role") or "") != "user":
            continue
        text = str(item.get("content") or "").strip()
        if text:
            texts.append(text)
        if len(texts) >= max_turns:
            break
    texts.reverse()
    return " ".join(texts)


def _extract_subjects_from_text(text: str) -> list[str]:
    subjects: list[str] = []
    for subject in _SUBJECT_NAMES:
        if subject in text and subject not in subjects:
            subjects.append(subject)
    compact = re.sub(r"\s+", "", text)
    for combo in re.findall(r"[物史化生政地]{2,6}", compact):
        for char in combo:
            subject = _SUBJECT_ABBREVIATIONS.get(char)
            if subject and subject not in subjects:
                subjects.append(subject)
    return subjects


def _format_recent_user_context(text: str) -> str:
    parts: list[str] = []
    for province in _PROVINCE_NAMES:
        if province in text:
            parts.append(f"省份={province}")
            break
    score_match = re.search(r"(\d{3})\s*分", text)
    if score_match:
        parts.append(f"分数={score_match.group(1)}")
    subjects = _extract_subjects_from_text(text)
    if subjects:
        parts.append(f"选科={'、'.join(subjects[:3])}")
    return "；".join(parts)


def _prompt_context_parts(user_text: str) -> list[str]:
    parts: list[str] = []
    if "普通家庭" in user_text:
        parts.append("普通家庭")
    if "女生" in user_text or "女孩" in user_text or "女孩子" in user_text:
        parts.append("女生")
    elif "男生" in user_text or "男孩" in user_text or "男孩子" in user_text:
        parts.append("男生")
    return parts


def _format_score_detail(score_detail: ScoreDetail | None, *, user_text: str = "") -> str:
    prompt_context = "、".join(_prompt_context_parts(user_text))
    if score_detail is None:
        recent_context = _format_recent_user_context(user_text)
        if recent_context:
            prefix = f"已参考你在对话里提供的基础信息：{recent_context}"
            if prompt_context:
                return f"{prefix}；同时参考本轮提到的{prompt_context}约束；因为还没有完整结合分数、省份、选科和方案位置，这里先做方向判断，不直接给最终倾向。"
            return f"{prefix}；因为还没有完整结合分数、省份、选科和方案位置，这里先做方向判断，不直接给最终倾向。"
        if prompt_context:
            return f"本轮先按你提到的{prompt_context}等约束做通用判断；当前会话还缺分数、选科和省份，所以先不直接给最终倾向。"
        return "当前会话还没有完整分数、选科和省份信息，所以先不直接给最终倾向。"
    subjects = "、".join(score_detail.subject_list or []) or "未知"
    base = (
        "已参考当前会话基础信息："
        f"省份={score_detail.province or '未知'}；"
        f"分数={score_detail.total_score or '未知'}；"
        f"选科={subjects}；"
        f"性别={score_detail.sex or '未知'}；"
        f"模式={score_detail.volunteer_model or '未知'}"
    )
    if prompt_context:
        return f"{base}；同时参考本轮提到的{prompt_context}约束"
    return base


def _format_init_profile(init_profile: UserProfile | None) -> str:
    if init_profile is None:
        return ""
    parts: list[str] = []
    positive_majors = "、".join(init_profile.major.level2[:4] or init_profile.major.level3[:4] or [])
    negative_majors = "、".join(init_profile.major.negative_level2[:4] or init_profile.major.negative_level3[:4] or [])
    regions = "、".join(init_profile.city.province[:4] or [])
    if positive_majors:
        parts.append(f"已表达偏好专业：{positive_majors}")
    if negative_majors:
        parts.append(f"已表达排除专业：{negative_majors}")
    if regions:
        parts.append(f"已表达地域偏好：{regions}")
    return "；".join(parts)


def _major_category_name(major_name: str, batch: str | None = None) -> str:
    mappings = associate_major_mappings if batch == "02" else bachelor_major_mappings
    return str((mappings.get("level3_to_level2") or {}).get(major_name) or "").strip()


@dataclass(frozen=True, slots=True)
class _MajorCategoryProfile:
    path: str
    threshold: str
    stability: str
    cost: str
    stability_score: int
    barrier_score: int


_MAJOR_CATEGORY_PROFILES: dict[str, _MajorCategoryProfile] = {
    "法学类": _MajorCategoryProfile(
        path="法律职业、公检法、司法行政、纪检监察、合规风控、公共事务等方向",
        threshold="法考、案例训练、文字表达和逻辑论证要求较高",
        stability="考公相关岗位覆盖较多，但早期路径受法考、实习和平台影响明显",
        cost="专业壁垒清楚，上限不低；如果兴趣不强，前期试错成本偏高",
        stability_score=3,
        barrier_score=5,
    ),
    "财政学类": _MajorCategoryProfile(
        path="财政、税务、审计、预算管理、银行、国企财务和政府财会类岗位",
        threshold="需要财税基础、政策理解和数据处理能力，证书压力相对分散",
        stability="岗位口径清楚，考公考编、国企和企业财务都能承接",
        cost="路径更可预期，对普通家庭降低试错成本更友好",
        stability_score=5,
        barrier_score=3,
    ),
    "金融学类": _MajorCategoryProfile(
        path="银行、证券、保险、投融资、金融科技、监管和企业财务方向",
        threshold="对学校层次、城市平台、数理和实习资源比较敏感",
        stability="银行、国企和监管类路径相对稳，市场化金融岗位波动更大",
        cost="上限和平台相关度高，普通家庭要重点看城市与院校层次",
        stability_score=3,
        barrier_score=4,
    ),
    "经济学类": _MajorCategoryProfile(
        path="宏观研究、产业分析、数据分析、政策研究、考公和企事业综合岗",
        threshold="更依赖数学、统计、写作和升学深造来形成竞争力",
        stability="岗位面较宽，但本科直接对口度不如财税、会计等方向清晰",
        cost="适合继续深造或复合能力强的学生，直接就业需要提前规划技能",
        stability_score=3,
        barrier_score=3,
    ),
    "工商管理类": _MajorCategoryProfile(
        path="会计、审计、财务、人力、运营、市场和企业管理相关岗位",
        threshold="岗位分化明显，会计审计更看证书和实操，管理类更看平台与经验",
        stability="财会审计方向稳定性较好，泛管理方向需要更强实习和组织能力",
        cost="如果选到具体岗位口径清楚的专业，试错成本较低",
        stability_score=4,
        barrier_score=3,
    ),
    "电子商务类": _MajorCategoryProfile(
        path="电商运营、跨境平台运营、数字营销、供应链协同、用户增长和中小企业线上业务",
        threshold="需要英语或外贸基础、平台规则理解、数据分析、营销投放和实操项目经验",
        stability="岗位机会多但平台变化快，普通院校也能就业，关键看城市产业、实习和个人运营能力",
        cost="路径上手较快、试错成本相对可控，但要避免只学泛管理不做项目",
        stability_score=3,
        barrier_score=3,
    ),
    "计算机类": _MajorCategoryProfile(
        path="软件开发、数据、人工智能、信息安全、企事业信息化和数字化岗位",
        threshold="对数学、编程训练、项目实践和持续学习要求高",
        stability="岗位需求大，但竞争和技术迭代也快，学校与能力差异会被放大",
        cost="投入产出上限高，适合能接受强训练和持续学习的学生",
        stability_score=4,
        barrier_score=4,
    ),
    "中国语言文学类": _MajorCategoryProfile(
        path="教师、编辑出版、新媒体、行政文秘、公务员和事业单位综合岗",
        threshold="重阅读写作、表达、材料组织和长期积累",
        stability="考公、事业单位和教师方向承接较好，市场化岗位需要作品和实习",
        cost="对普通家庭偏稳，但要注意就业城市和教师资格等路径准备",
        stability_score=4,
        barrier_score=3,
    ),
    "新闻传播学类": _MajorCategoryProfile(
        path="内容策划、新媒体运营、品牌传播、广告、公关、短视频与融媒体编辑等方向",
        threshold="重写作表达、选题判断、作品集、热点理解、实习经历和平台工具使用",
        stability="岗位面较宽但行业波动明显，城市资源、作品积累和学校平台会显著影响就业质量",
        cost="适合表达和内容兴趣强的学生，普通家庭要重点控制院校学费和就业城市试错成本",
        stability_score=2,
        barrier_score=3,
    ),
    "教育学类": _MajorCategoryProfile(
        path="教师、教培、教育管理、课程产品、心理与学生发展服务",
        threshold="看教师资格、学科能力、表达能力和实习实践",
        stability="教师编和学校岗位稳定，但地区招聘和学段学科差异较大",
        cost="路径相对清楚，适合偏稳定和愿意长期做教育服务的学生",
        stability_score=4,
        barrier_score=3,
    ),
    "公共管理类": _MajorCategoryProfile(
        path="政府事务、公共服务、行政管理、人社、社保、基层治理和企事业综合岗",
        threshold="看政策理解、材料写作、沟通协调和实习经历",
        stability="体制内方向匹配度较高，但市场化对口岗位相对分散",
        cost="适合明确考公考编或公共服务方向的学生",
        stability_score=4,
        barrier_score=2,
    ),
    "临床医学类": _MajorCategoryProfile(
        path="临床医生、规培、专科医生、医院和基层医疗卫生体系",
        threshold="学制长、学习强度高，执业资格、规培和升学要求明确",
        stability="职业壁垒强、长期稳定性好，但前期投入和时间成本高",
        cost="适合强医学兴趣、抗压能力强且能接受长周期培养的学生",
        stability_score=4,
        barrier_score=5,
    ),
    "口腔医学类": _MajorCategoryProfile(
        path="口腔临床、口腔修复、正畸、医院口腔科和口腔机构",
        threshold="医学基础、动手能力、执业资格和长期临床训练要求高",
        stability="专业壁垒强，就业场景相对清晰，但院校层次和培养质量很重要",
        cost="投入周期长，上限较好，适合愿意走医学技能路线的学生",
        stability_score=4,
        barrier_score=5,
    ),
    "电子信息类": _MajorCategoryProfile(
        path="通信、芯片、硬件、嵌入式、电子工程、智能终端和制造业研发",
        threshold="数理、电路、编程和工程实践要求较高",
        stability="产业需求较强，但岗位质量与城市、学校和实践能力相关",
        cost="适合能接受工科训练、愿意做工程研发或技术应用的学生",
        stability_score=4,
        barrier_score=4,
    ),
    "自动化类": _MajorCategoryProfile(
        path="控制工程、智能制造、机器人、工业自动化、嵌入式和生产系统",
        threshold="控制、数学、电子、编程和工程实践要求较高",
        stability="制造业和工程岗位承接面较宽，继续深造可提升上限",
        cost="适合工科基础较好、愿意做工程系统和技术应用的学生",
        stability_score=4,
        barrier_score=4,
    ),
}


def _major_compare_profile(major_name: str, batch: str | None = None) -> tuple[str, _MajorCategoryProfile | None]:
    category = _major_category_name(major_name, batch)
    return category, _MAJOR_CATEGORY_PROFILES.get(category)


def _render_major_profile_line(major_name: str, batch: str | None = None) -> str:
    category, profile = _major_compare_profile(major_name, batch)
    label = f"{major_name}（{category}）" if category else major_name
    if profile is None:
        focus = "课程适配、升学或证书要求、就业去向、目标地区岗位供给、学校层次和录取概率"
        if category:
            return f"{label}：当前没有沉淀专门画像，建议按{focus}逐项比较。"
        return f"{label}：建议按{focus}逐项比较。"
    return (
        f"{label}：就业路径主要看{profile.path}；门槛是{profile.threshold}；"
        f"稳定性上，{profile.stability}；试错成本上，{profile.cost}。"
    )


def _render_major_compare_decision_line(
    major_name1: str,
    major_name2: str,
    batch: str | None = None,
) -> str:
    _, profile1 = _major_compare_profile(major_name1, batch)
    _, profile2 = _major_compare_profile(major_name2, batch)
    if profile1 is None or profile2 is None:
        return (
            "选择建议：如果更看重普通家庭的稳就业和低试错成本，优先看岗位口径更清楚、"
            "培养周期更可控、普通院校也能承接的方向；如果更看重长期上限，"
            "再看专业壁垒、升学空间和自己能否持续投入。"
        )

    stable_major = None
    if abs(profile1.stability_score - profile2.stability_score) >= 1:
        stable_major = major_name1 if profile1.stability_score > profile2.stability_score else major_name2

    barrier_major = None
    if abs(profile1.barrier_score - profile2.barrier_score) >= 1:
        barrier_major = major_name1 if profile1.barrier_score > profile2.barrier_score else major_name2

    parts: list[str] = []
    if stable_major:
        parts.append(f"稳就业、可预期路径和降低试错成本优先时，先重点看{stable_major}")
    if barrier_major and barrier_major != stable_major:
        parts.append(f"强兴趣、长期壁垒和上限优先时，可以重点看{barrier_major}")
    if not parts:
        parts.append("两者稳定性和专业壁垒接近时，要把学校层次、城市机会、录取概率和本人兴趣放到同一张表里比较")
    return f"{'；'.join(parts)}。最终还要结合具体学校层次、城市、录取概率和是否愿意投入对应训练。"


def render_missing_weight_major_compare_reply(
    *,
    major_name1: str,
    major_name2: str,
    request_context: RequestContext,
) -> str:
    """Render a bounded user-facing answer for the known missing-weight tool state."""
    user_text = _recent_user_text(request_context) or _latest_user_text(request_context)
    score_context = _format_score_detail(request_context.score_detail, user_text=user_text)
    profile_context = _format_init_profile(request_context.init_profile)
    context_line = f"{score_context}{'；' + profile_context if profile_context else ''}".strip("；")
    sections = [
        f"这轮先按通用维度看 {major_name1} vs {major_name2}。因为还没有完整结合分数、省份、选科和方案位置，我先给你一个可参考的方向判断。",
    ]
    if context_line:
        sections.extend(
            [
                "",
                "**当前会话参考**",
                f"- {context_line}",
            ]
        )
    sections.extend(
        [
            "",
            "**本次边界**",
            "- 这次只做专业取舍分析，不会把任何专业记成偏好，也不会改方案。",
        ]
    )
    sections.extend(
        [
            "",
            f"**{major_name1}**",
            f"- {_render_major_profile_line(major_name1, request_context.batch)}",
            "",
            f"**{major_name2}**",
            f"- {_render_major_profile_line(major_name2, request_context.batch)}",
            "",
            "**选择建议**",
            f"- {_render_major_compare_decision_line(major_name1, major_name2, request_context.batch)}",
            "",
            "**下一步**",
            "- 可以把目标地区和可接受学校层次加进来，再看它们在当前方案和候选里的实际院校质量、录取概率和城市机会。",
        ]
    )
    return "\n".join(sections)
