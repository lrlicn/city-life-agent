"""自定义工具：城市到手工资计算器（ReAct 工具调用演示）。

⚠️ 说明：以下社保/公积金比例、缴费基数上下限均为「演示用简化参数」，
    仅用于学习展示工具调用流程与领域建模，不代表各城市真实政策，
    实际请以当地官方发布为准。

Phase 3 升级点：
- 缴费基数上下限（clamp）：月薪超出上限按上限、低于下限按下限计
- 专项附加扣除参数化：deductions 传入月度扣除额
- 估算区间 + 口径假设：输出当前参数到手值 + 申报/未申报专项扣除的区间
"""

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
