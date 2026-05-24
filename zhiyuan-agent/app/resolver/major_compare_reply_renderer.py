"""User-facing renderers for readonly major comparison tool states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.data.major_data import associate_major_mappings, bachelor_major_mappings

if TYPE_CHECKING:
    from app.agent.context import RequestContext, ScoreDetail
    from app.schemas.user_profile import UserProfile


def is_missing_weight_major_compare_result(result_text: str) -> bool:
    return "暂时没有拿到当前会话可用的个性化量化权重数据" in str(result_text or "")


def _format_score_detail(score_detail: ScoreDetail | None) -> str:
    if score_detail is None:
        return "当前会话还没有完整分数、选科、省份和性别信息。"
    subjects = "、".join(score_detail.subject_list or []) or "未知"
    return (
        "已参考当前会话基础信息："
        f"省份={score_detail.province or '未知'}；"
        f"分数={score_detail.total_score or '未知'}；"
        f"选科={subjects}；"
        f"性别={score_detail.sex or '未知'}；"
        f"模式={score_detail.volunteer_model or '未知'}"
    )


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
    return f"选择建议：{'；'.join(parts)}。最终还要结合具体学校层次、城市、录取概率和是否愿意投入对应训练。"


def render_missing_weight_major_compare_reply(
    *,
    major_name1: str,
    major_name2: str,
    request_context: RequestContext,
) -> str:
    """Render a bounded user-facing answer for the known missing-weight tool state."""
    score_context = _format_score_detail(request_context.score_detail)
    profile_context = _format_init_profile(request_context.init_profile)
    context_line = f"{score_context}{'；' + profile_context if profile_context else ''}"
    return "\n".join(
        [
            f"这轮先按通用维度看 {major_name1} vs {major_name2}。当前没有拿到可用的个性化量化评分，所以不直接说系统分数谁更高。",
            "",
            f"- {context_line}",
            f"- {_render_major_profile_line(major_name1, request_context.batch)}",
            f"- {_render_major_profile_line(major_name2, request_context.batch)}",
            f"- {_render_major_compare_decision_line(major_name1, major_name2, request_context.batch)}",
            "- 下一步可以把目标地区和可接受学校层次加进来，再看它们在当前方案和候选里的实际院校质量、录取概率和城市机会。",
        ]
    )
