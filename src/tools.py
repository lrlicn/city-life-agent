"""自定义工具：城市到手工资计算器（ReAct 工具调用演示）。

⚠️ 说明：以下社保/公积金比例、缴费基数上下限均为「演示用简化参数」，
    仅用于学习展示工具调用流程与领域建模，不代表各城市真实政策，
    实际请以当地官方发布为准。

Phase 3 升级点：
- 缴费基数上下限（clamp）：月薪超出上限按上限、低于下限按下限计
- 专项附加扣除参数化：deductions 传入月度扣除额
- 估算区间 + 口径假设：输出当前参数到手值 + 申报/未申报专项扣除的区间
"""

import re
import time
from pathlib import Path

from src import interaction

# 报告导出落盘目录：<项目根>/data/exports（首次导出自动创建；PDF 由前端「打印」生成，后端只写 Markdown）
EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"

# 演示城市参数表（非官方，仅教学用）：
#   social/fund = 个人社保/公积金比例；threshold = 个税起征点
#   base_floor/base_cap = 缴费基数上下限（演示值）
CITY_PARAMS = {
    "上海": {"social": 0.105, "fund": 0.07, "threshold": 5000, "base_floor": 7000, "base_cap": 36000},
    "北京": {"social": 0.102, "fund": 0.12, "threshold": 5000, "base_floor": 6300, "base_cap": 34000},
    "深圳": {"social": 0.105, "fund": 0.05, "threshold": 5000, "base_floor": 2360, "base_cap": 33000},
    "广州": {"social": 0.105, "fund": 0.05, "threshold": 5000, "base_floor": 2300, "base_cap": 34000},
}


def _income_tax(taxable: float) -> tuple[float, str]:
    """月度简化个税三档（3%/10%/20%），返回 (税额, 档位名)。

    注意：taxable 是「月」应纳税所得额，套月度档位（3000/12000），
    不能套年综合税率表（36000/144000），否则月值会被错判进低档。
    """
    taxable = max(taxable, 0.0)
    if taxable <= 3000:
        return taxable * 0.03, "3%"
    elif taxable <= 12000:
        return taxable * 0.10 - 210, "10%"   # 速算扣除 210（对应年 2520）
    else:
        return taxable * 0.20 - 1410, "20%"  # 速算扣除 1410（对应年 16920）


def compute_salary(
    city: str,
    monthly_salary: float,
    deductions: float = 0.0,
) -> str:
    """计算某城市月薪的到手收入（扣除社保、公积金、个税）。

    体现「负责任的 AI 输出」：给定参数返回确定性单点，同时给出
    口径假设与估算区间（专项附加扣除申报与否的影响）。

    Args:
        city: 城市名，如 "上海"、"北京"、"深圳"。
        monthly_salary: 税前月薪（元）。
        deductions: 月度专项附加扣除额（元），默认 0（未申报）。
    """
    if city not in CITY_PARAMS:
        return f"暂不支持城市：{city}"

    p = CITY_PARAMS[city]

    # 1. 缴费基数上下限：clamp 到 [floor, cap]（月薪超限按限值计）
    base = min(max(monthly_salary, p["base_floor"]), p["base_cap"])
    social = base * p["social"]
    fund = base * p["fund"]

    if monthly_salary > p["base_cap"]:
        clamp_note = f"（月薪超出上限 {p['base_cap']:.0f}，基数按下限封顶）"
    elif monthly_salary < p["base_floor"]:
        clamp_note = f"（月薪低于下限 {p['base_floor']:.0f}，基数按下限保底）"
    else:
        clamp_note = "（基数=实际月薪）"

    # 2. 个税：应纳税所得额 = 月薪 − 三险一金 − 起征点 − 专项附加扣除
    taxable = monthly_salary - social - fund - p["threshold"] - deductions
    tax, band = _income_tax(taxable)
    net = monthly_salary - social - fund - tax

    # 3. 估算区间：专项附加扣除申报与否（演示：0 元 vs 2000 元）
    tax0, _ = _income_tax(monthly_salary - social - fund - p["threshold"] - 0.0)
    tax2, _ = _income_tax(monthly_salary - social - fund - p["threshold"] - 2000.0)
    net_no_ded = monthly_salary - social - fund - tax0          # 未申报（个税高→到手低）
    net_with_ded = monthly_salary - social - fund - tax2        # 申报 2000（个税低→到手高）

    return (
        f"{city}月薪 {monthly_salary:.0f} 元到手测算（估算）：\n"
        f"  缴费基数 ≈ {base:.0f} 元（{p['base_floor']:.0f}~{p['base_cap']:.0f}）{clamp_note}\n"
        f"  社保(个人) ≈ {social:.0f} 元（{p['social']*100:.1f}%）\n"
        f"  公积金(个人) ≈ {fund:.0f} 元（{p['fund']*100:.0f}%）\n"
        f"  个税 ≈ {max(tax, 0):.0f} 元（{band}档，含专项附加扣除 {deductions:.0f}）\n"
        f"  到手 ≈ {net:.0f} 元\n"
        f"  估算区间：约 {net_no_ded:.0f} ~ {net_with_ded:.0f} 元"
        f"（未申报 ~ 申报 2000 元专项附加）\n"
        f"  口径：到手=月薪−社保−公积金−个税；个税起征点 {p['threshold']:.0f}/月；"
        f"未计累计预扣法与年终奖；以上为演示参数，以官方为准。"
    )


# 租房演示惯例（非官方，仅教学用）：
#   agency_default_rate = 中介费默认占月租金比例（上海常见约半月租金）
#   deposit_default_months = 常见押付月数
RENT_DEFAULTS = {
    "上海": {"agency_default_rate": 0.5, "deposit_default_months": 1.0},
    "北京": {"agency_default_rate": 1.0, "deposit_default_months": 1.0},
    "深圳": {"agency_default_rate": 0.5, "deposit_default_months": 1.0},
    "广州": {"agency_default_rate": 0.5, "deposit_default_months": 1.0},
}


def compute_rent(
    city: str,
    monthly_rent: float,
    deposit_months: float | None = None,
    agency_fee_rate: float | None = None,
    property_fee: float = 0.0,
    utility: float = 0.0,
    months: int = 12,
) -> str:
    """计算某城市租房的成本构成（押金 / 中介费 / 首月支出 / 月均 / 年总）。

    输出固定格式文本，便于后端正则提取结构化数据供前端画图（同 compute_salary 模式）。

    Args:
        city: 城市名，如 "上海"、"北京"。
        monthly_rent: 月租金（元/月）。
        deposit_months: 押金月数；缺省按城市惯例。
        agency_fee_rate: 中介费率（占月租金）；缺省按城市惯例。
        property_fee: 物业费/月（元），默认 0。
        utility: 水电网/月（元），默认 0。
        months: 租期（月），默认 12。
    """
    if city not in RENT_DEFAULTS:
        return f"暂不支持城市：{city} 的租房测算"

    d = RENT_DEFAULTS[city]
    if deposit_months is None:
        deposit_months = d["deposit_default_months"]
    if agency_fee_rate is None:
        agency_fee_rate = d["agency_default_rate"]

    deposit = monthly_rent * deposit_months          # 押金（可退）
    agency = monthly_rent * agency_fee_rate          # 中介费（一次性，不退）
    first_month = monthly_rent + deposit + agency + property_fee + utility  # 首月现金支出
    monthly_recurring = monthly_rent + property_fee + utility              # 月均持续成本
    year_total = monthly_recurring * months + agency                        # 年总成本（押金可退不计入）

    return (
        f"{city}租房成本测算（月租金 {monthly_rent:.0f} 元）：\n"
        f"  押金 ≈ {deposit:.0f} 元（{deposit_months:g} 个月，退租可退）\n"
        f"  中介费 ≈ {agency:.0f} 元（{agency_fee_rate*100:.0f}% 月租金，一次性）\n"
        f"  首月一次性支出 ≈ {first_month:.0f} 元（押金+中介费+首月租金+物业水电）\n"
        f"  月均生活成本 ≈ {monthly_recurring:.0f} 元（租金+物业+水电网）\n"
        f"  年总成本 ≈ {year_total:.0f} 元（{months} 个月，押金可退不计入）\n"
        f"  口径：押金/中介费惯例为演示参数，实际以当地房源与中介约定为准。"
    )


# 通勤演示参数（非官方，仅教学用）：
#   subway_start/subway_per_km = 地铁起步价与每公里加价（简化线性计价）
#   taxi_start/taxi_per_km     = 出租起步价与里程费
#   drive_cost_per_km          = 自驾每公里综合成本（油/电+磨损）
#   parking_monthly            = 办公地月停车费分摊；ebike_monthly = 电动车充电+磨损
COMMUTE_DEFAULTS = {
    "上海": {"subway_start": 3.0, "subway_per_km": 0.55, "taxi_start": 14.0, "taxi_per_km": 2.7,
             "drive_cost_per_km": 0.85, "parking_monthly": 800.0, "ebike_monthly": 60.0},
    "北京": {"subway_start": 3.0, "subway_per_km": 0.50, "taxi_start": 13.0, "taxi_per_km": 2.3,
             "drive_cost_per_km": 0.90, "parking_monthly": 900.0, "ebike_monthly": 55.0},
    "深圳": {"subway_start": 2.0, "subway_per_km": 0.50, "taxi_start": 12.5, "taxi_per_km": 2.4,
             "drive_cost_per_km": 0.80, "parking_monthly": 700.0, "ebike_monthly": 60.0},
    "广州": {"subway_start": 2.0, "subway_per_km": 0.45, "taxi_start": 12.0, "taxi_per_km": 2.6,
             "drive_cost_per_km": 0.75, "parking_monthly": 600.0, "ebike_monthly": 60.0},
}


def compute_commute(
    city: str,
    one_way_km: float,
    days_per_month: int = 22,
) -> str:
    """按出行方式测算月度通勤成本（地铁公交 / 电动车 / 自驾 / 打车）。

    输出固定格式文本，便于后端正则提取结构化数据供前端画图（同 compute_salary 模式）。

    Args:
        city: 城市名，如 "上海"、"北京"。
        one_way_km: 单程通勤距离（公里）。
        days_per_month: 每月通勤天数，默认 22（按 5 天×4.4 周估）。
    """
    if city not in COMMUTE_DEFAULTS:
        return f"暂不支持城市：{city} 的通勤测算"
    if one_way_km <= 0:
        return "单程距离需大于 0 公里"

    c = COMMUTE_DEFAULTS[city]
    trips = days_per_month * 2  # 每月往返总次数（双程）

    subway_once = c["subway_start"] + c["subway_per_km"] * one_way_km
    subway = subway_once * trips
    ebike = c["ebike_monthly"]                      # 充电+磨损按月折算，与距离弱相关（演示简化）
    drive = one_way_km * 2 * days_per_month * c["drive_cost_per_km"] + c["parking_monthly"]
    taxi_once = c["taxi_start"] + c["taxi_per_km"] * one_way_km
    taxi = taxi_once * trips

    options = {"地铁/公交": subway, "电动车": ebike, "自驾": drive, "打车": taxi}
    cheapest_name, cheapest_val = min(options.items(), key=lambda kv: kv[1])

    return (
        f"{city}通勤成本测算（单程 {one_way_km:g} 公里，每月 {days_per_month} 天×往返）：\n"
        f"  地铁/公交 ≈ {subway:.0f} 元/月（单程 {subway_once:.1f} 元）\n"
        f"  电动车 ≈ {ebike:.0f} 元/月（充电+磨损折算）\n"
        f"  自驾 ≈ {drive:.0f} 元/月（能耗+停车 {c['parking_monthly']:.0f} 元/月）\n"
        f"  打车 ≈ {taxi:.0f} 元/月（单程 {taxi_once:.0f} 元）\n"
        f"  最省 ≈ {cheapest_name} 约 {cheapest_val:.0f} 元/月\n"
        f"  口径：各计价为演示简化参数（未计阶梯票价/拼车/拥堵费）；"
        f"电动车未计头盔保险；实际以当地运价与通勤路线为准。"
    )


# 房贷演示参数（非官方，仅教学用）：
#   贷款类型之分 —— 商贷利率低于公积金可贷款额上限（首套），组合贷 = 公积金段 + 商贷段。
#   等额本息/等额本金为还款方式，与贷款类型正交：两段按各自利率分别测算再合计。
MORTGAGE_PARAMS = {
    "default": {"commercial_rate": 3.6, "provident_rate": 2.85},
    "cap_by_city": {  # 公积金最高贷款额（万元，演示值：首套/含补充公积金常见上限）
        "上海": 160, "北京": 120, "深圳": 90, "广州": 100, "杭州": 130, "成都": 80, "武汉": 100,
    },
}

# 贷款类型别名归一（模型可能填「公积金贷款」「组合」等）
_LOAN_TYPE_ALIASES = {
    "商贷": "商贷", "商业贷款": "商贷", "商业": "商贷",
    "公积金": "公积金", "公积金贷款": "公积金", "公积金贷": "公积金",
    "组合": "组合", "组合贷": "组合", "组合贷款": "组合", "商贷+公积金": "组合",
}


def compute_mortgage(
    loan_amount: float,
    years: int,
    annual_rate: float | None = None,
    city: str = "",
    loan_type: str = "商贷",
    provident_amount: float | None = None,
    provident_rate: float | None = None,
    commercial_rate: float | None = None,
) -> str:
    """测算房贷两种还款方式（等额本息 / 等额本金）的月供与总利息，支持商贷/公积金/组合贷。

    输出固定格式文本，便于后端正则提取结构化数据供前端画还款计划对比图与月供构成图。

    Args:
        loan_amount: 贷款总额（元）。
        years: 贷款年限（年）。
        annual_rate: 年利率（百分数，如 3.5 表示 3.5%）；商贷/纯公积金未填时按演示默认。
        city: 城市名（如 "上海"）；提供时按其公积金最高贷款额自动封顶拆分。
        loan_type: 贷款类型："商贷"（默认）/ "公积金" / "组合"（公积金 + 商贷）。
        provident_amount: 公积金贷款部分金额（元），组合/公积金类型下使用；缺省按公积金利率上限折算。
        provident_rate: 公积金年利率（百分数）；缺省按演示默认。
        commercial_rate: 商贷年利率（百分数）；缺省取 annual_rate 或演示默认。
    """
    if loan_amount <= 0:
        return "贷款总额需大于 0 元"
    if years <= 0:
        return "贷款年限需大于 0 年"

    lt = _LOAN_TYPE_ALIASES.get((loan_type or "商贷").strip())
    if lt is None:
        return f"暂不支持贷款类型：{loan_type}（可选：商贷 / 公积金 / 组合）"

    dp = MORTGAGE_PARAMS["default"]
    city_info = MORTGAGE_PARAMS["cap_by_city"].get((city or "").strip())
    cap = city_info * 10000 if city_info is not None else None
    comm_rate = commercial_rate if commercial_rate is not None else annual_rate
    prov_rate = provident_rate if provident_rate is not None else dp["provident_rate"]
    if comm_rate is None:
        comm_rate = dp["commercial_rate"]
    for r, label in ((comm_rate, "商贷"), (prov_rate, "公积金")):
        if r < 0:
            return f"{label}年利率不能为负"

    # 按类型拆出各计息段 (段名, 本金, 年利率)；额度校验优先于默认填充
    if lt == "商贷":
        parts = [("商贷", loan_amount, comm_rate)]
    elif lt == "公积金":
        amt = provident_amount if provident_amount is not None else loan_amount
        if cap is not None and amt > cap:
            return (f"公积金贷款额 {amt:.0f} 元超过 {city} 最高贷款额 {cap:.0f} 元（演示参数）；"
                    f"如需超出，请使用组合贷（公积金 {cap:.0f} + 商贷 {amt - cap:.0f}）")
        parts = [("公积金", amt, prov_rate)]
    else:  # 组合：公积金段先按城市上限封顶，剩余走商贷段
        want = provident_amount if provident_amount is not None else loan_amount
        prov = min(want, loan_amount)
        if cap is not None:
            note = f"（{city}公积金最高贷款额 {cap:.0f} 元，超出部分转商贷）" if want > cap else ""
            prov = min(prov, cap)
        else:
            note = ""
        rest = loan_amount - prov
        parts = [("公积金", prov, prov_rate)]
        if rest > 0:
            parts.append(("商贷", rest, comm_rate))
        if note:
            parts.append(("__note__", 0.0, note))

    n = int(round(years * 12))  # 总期数（月）

    # 分段测算 → 合计月供/总利息（等额本息各段月供相加；等额本金各段线性递减之和仍线性递减）
    seg, annuity_pay, annuity_interest, ep_first, ep_last, ep_interest = [], 0.0, 0.0, 0.0, 0.0, 0.0
    for name, principal, rate in parts:
        if name == "__note__":
            continue
        r = rate / 100 / 12
        if r == 0:
            a_pay = principal / n
        else:
            factor = (1 + r) ** n
            a_pay = principal * r * factor / (factor - 1)
        pp = principal / n
        f_first = pp + principal * r
        f_last = pp + pp * r
        seg.append({"type": name, "amount": round(principal), "rate": rate,
                    "annuity_pay": round(a_pay), "annuity_interest": round(a_pay * n - principal),
                    "ep_interest": round(principal * r * (n + 1) / 2)})
        annuity_pay += a_pay
        annuity_interest += a_pay * n - principal
        ep_first += f_first
        ep_last += f_last
        ep_interest += principal * r * (n + 1) / 2

    multi = len(seg) > 1
    save = annuity_interest - ep_interest  # 等额本金比等额本息少付的利息
    cheaper = "等额本金" if save >= 0 else "等额本息"

    if multi:
        merged = " / ".join(f"{s['type']} {s['rate']:g}%" for s in seg)
        head = f"房贷测算（贷款 {loan_amount:.0f} 元，组合贷：{merged}，{years} 年）："
        t_ann, t_ep = "合计等额本息月供", "合计等额本金首月"
    else:
        label = seg[0]["type"]
        head = f"房贷测算（贷款 {loan_amount:.0f} 元，{label}，年利率 {seg[0]['rate']:g}%，{years} 年）："
        t_ann, t_ep = f"{label}等额本息月供", f"{label}等额本金首月"

    lines = [
        head,
        f"  {t_ann} ≈ {annuity_pay:.0f} 元/月（每月固定）",
        f"  {t_ann.replace('月供', '总利息')} ≈ {annuity_interest:.0f} 元",
        f"  {t_ep} ≈ {ep_first:.0f} 元/月（逐月递减）",
    ]
    if multi:
        lines.append(f"  合计等额本金末月 ≈ {ep_last:.0f} 元/月（末期最低）")
        lines.append(f"  合计等额本金总利息 ≈ {ep_interest:.0f} 元")
    else:
        lines.append(f"  等额本金末月 ≈ {ep_last:.0f} 元/月（末期最低）")
        lines.append(f"  等额本金总利息 ≈ {ep_interest:.0f} 元")
    lines.append(f"  利息更省 ≈ {cheaper} 约省 {abs(save):.0f} 元")
    if multi:
        lines.append("  月供构成拆分（等额本息口径）：")
        for s in seg:
            lines.append(f"    - {s['type']} 贷款 {s['amount']:.0f} 元 @ {s['rate']:g}%，月供 ≈ {s['annuity_pay']:.0f} 元")
        note = next((p[2] for p in parts if p[0] == "__note__"), "")
        if note:
            lines.append(f"  额度说明{note}")

    tail = "口径：按月复利简化模型（标准公式，多段分别计息再合计）；利率/公积金上限为演示参数；"
    tail += "未计贴息/浮动利率/手续费与提前还款；实际以银行审批、当地公积金中心与借款合同为准。"
    if multi:
        tail += "组合贷月供为两段合计。"
    lines.append(f"  {tail}")
    return "\n".join(lines)


# 生活成本指数演示参数（非官方，仅教学用）：
#   各城市四类支出的典型月度成本（元），用于按「基准城市 = 100」折算相对指数。
#   租房按整租一居、餐饮按在外就餐、交通按通勤、日用按商超购物（均为演示均值）。
COST_CATEGORIES = ["租房", "餐饮", "交通", "日用"]
COST_INDEX = {
    "上海": {"租房": 5500, "餐饮": 2200, "交通": 700, "日用": 1600},
    "北京": {"租房": 5800, "餐饮": 2100, "交通": 750, "日用": 1650},
    "深圳": {"租房": 5000, "餐饮": 2000, "交通": 650, "日用": 1550},
    "广州": {"租房": 3800, "餐饮": 1800, "交通": 600, "日用": 1400},
    "杭州": {"租房": 4200, "餐饮": 1900, "交通": 600, "日用": 1450},
    "成都": {"租房": 2800, "餐饮": 1500, "交通": 500, "日用": 1250},
    "武汉": {"租房": 2600, "餐饮": 1500, "交通": 500, "日用": 1200},
}


def compute_cost_index(base_city: str, cities: str) -> str:
    """以某城市为基准（=100）测算若干城市的生活成本相对指数（租房/餐饮/交通/日用四类）。

    输出固定格式文本，便于后端正则提取结构化数据供前端画分组柱状对比图（同 compute_commute 模式）。

    Args:
        base_city: 基准城市名（其指数记为 100），如 "上海"。
        cities: 参与对比的城市列表，用逗号分隔，如 "上海,北京,广州,成都"。
    """
    if base_city not in COST_INDEX:
        return f"暂不支持基准城市：{base_city}"

    # 解析待对比城市（兼容中英文逗号、顿号、空格），去重保序，只留支持的
    normalized = (cities or "").replace("，", ",").replace("、", ",").replace(" ", ",")
    names: list[str] = []
    for n in normalized.split(","):
        n = n.strip()
        if n and n in COST_INDEX and n not in names:
            names.append(n)
    if not names:
        return f"没有可对比的城市（支持：{'、'.join(COST_INDEX)}）"

    # 基准城市保证在列表里且排首位
    if base_city in names:
        names.remove(base_city)
    names.insert(0, base_city)

    base = COST_INDEX[base_city]
    base_total = sum(base[c] for c in COST_CATEGORIES)

    lines = [f"生活成本指数对比（基准：{base_city} = 100）："]
    comps: dict[str, int] = {}
    for name in names:
        cost = COST_INDEX[name]
        idx = [round(cost[c] / base[c] * 100) for c in COST_CATEGORIES]
        comp = round(sum(cost[c] for c in COST_CATEGORIES) / base_total * 100)
        comps[name] = comp
        cat_part = " / ".join(f"{c} {v}" for c, v in zip(COST_CATEGORIES, idx))
        lines.append(f"  {name}：综合 {comp}（{cat_part}）")

    cheapest_name, cheapest_comp = min(comps.items(), key=lambda kv: kv[1])
    lines.append(f"  最省 ≈ {cheapest_name} 综合 {cheapest_comp}")
    lines.append(
        f"  口径：指数以基准城市=100 折算（>100 更贵、<100 更便宜）；"
        f"分类成本为演示简化均值，实际以个人消费结构与当地行情为准。"
    )
    return "\n".join(lines)


async def ask_user(question: str, options: str) -> str:
    """向用户提出一个带候选项的澄清问题并暂停等待其点选。

    这是「生成中途让用户选择」的能力：调用后会暂停整条回答流，直到用户
    在前端点选某个选项，然后返回该选项文本作为工具输出，你据此继续测算/回答。

    使用时机（克制）：仅当某个关键入参缺失、且无法从检索语料确定时才调用；
    能从资料/常识合理推断的，直接推断并在回答里注明口径，不要打断用户。

    Args:
        question: 要问用户的问题，一句话说清缺什么信息。
        options: 2~4 个互斥候选项，用英文逗号分隔（如 "商贷,公积金,组合贷"）。
    """
    return await interaction.await_choice(question, options)


def _safe_stem(title: str) -> str:
    """把报告标题归一为安全的文件名主干：保留中文/字母/数字/下划线/短横，其余折叠为下划线。"""
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (title or "").strip()).strip("_")
    return stem[:40] or "report"


def export_report(title: str, content: str) -> str:
    """把一份完整报告的正文落盘为 Markdown 文件，返回可下载链接。

    ⚠️ 这是一次「有副作用」的动作：会在服务器 data/exports/ 下写一个 .md 文件。
    因此当「需审批」开关开启时，调用前会先弹出确认卡片，经用户批准才执行。

    使用时机：仅当用户明确要「导出报告 / 生成可下载的报告文件」时才调用；
    content 传入你已按 report 模式产出的完整报告正文（Markdown）。

    Args:
        title: 报告标题（用于文件名与展示）。
        content: 报告正文（Markdown 全文）。
    """
    if not content or not content.strip():
        return "报告正文为空，无法导出；请先产出完整报告内容再调用 export_report。"

    body = content.strip()
    stem = _safe_stem(title)
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{stem}_{ts}.md"

    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        (EXPORT_DIR / filename).write_text(body, encoding="utf-8")
    except OSError as e:  # noqa: BLE001
        return f"报告导出失败：写入文件出错（{e}）。"

    url = f"/api/exports/{filename}"
    return (
        f"报告已导出（Markdown）：\n"
        f"  标题：{(title or stem).strip()}\n"
        f"  文件：{filename}\n"
        f"  下载：{url}\n"
        f"  格式：Markdown\n"
        f"  字数：{len(body)} 字符\n"
        f"  说明：文件已保存在服务器 data/exports/，可通过下载链接获取；"
        f"如需 PDF，请在页面用「打印/另存为 PDF」生成。"
    )
