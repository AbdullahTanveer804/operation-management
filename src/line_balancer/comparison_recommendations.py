"""
Takt vs Pitch Comparison Recommendations Generator

Generates plain-English recommendation text summarizing Takt vs Pitch
Comparison results, driven entirely by the computed comparison numbers.
"""

from typing import Dict, List


def generate_takt_vs_pitch_recommendations(comparison_data: Dict) -> List[str]:
    """
    Generate 2-4 plain-English summary and recommendation sentences
    based strictly on the computed comparison output.
    
    Args:
        comparison_data: Dictionary output from calculate_takt_vs_pitch_comparison
                         containing 'before', 'method_a', 'method_b', 'comparison', etc.
                         
    Returns:
        List of 2-4 recommendation sentences (List[str])
    """
    if not comparison_data:
        return []

    before = comparison_data.get("before", {})
    method_a = comparison_data.get("method_a", {})
    method_b = comparison_data.get("method_b", {})

    before_mp = before.get("total_manpower", 0)
    mp_a = method_a.get("total_manpower", 0)
    mp_b = method_b.get("total_manpower", 0)

    eff_a = method_a.get("efficiency_balancing_rate", 0.0)
    delay_a = method_a.get("comparison_balance_delay", 0.0)
    eff_b = method_b.get("efficiency_balancing_rate", 0.0)
    delay_b = method_b.get("comparison_balance_delay", 0.0)

    sentences: List[str] = []

    # =========================================================================
    # 1. Operator Count Comparison
    # =========================================================================
    if mp_a < mp_b:
        diff = mp_b - mp_a
        saved = before_mp - mp_a
        diff_str = f"{diff} fewer operator{'s' if diff != 1 else ''}"
        saved_str = f", saving {saved} operator{'s' if saved != 1 else ''} vs baseline ({before_mp})" if before_mp > 0 else ""
        sentences.append(
            f"Method A requires {mp_a} operators compared to {mp_b} for Method B ({diff_str}{saved_str})."
        )
    elif mp_b < mp_a:
        diff = mp_a - mp_b
        saved = before_mp - mp_b
        diff_str = f"{diff} fewer operator{'s' if diff != 1 else ''}"
        saved_str = f", saving {saved} operator{'s' if saved != 1 else ''} vs baseline ({before_mp})" if before_mp > 0 else ""
        sentences.append(
            f"Method B requires {mp_b} operators compared to {mp_a} for Method A ({diff_str}{saved_str})."
        )
    else:
        saved = before_mp - mp_a
        saved_str = f", saving {saved} operator{'s' if saved != 1 else ''} vs baseline ({before_mp})" if before_mp > 0 else ""
        sentences.append(
            f"Both Method A and Method B require an identical {mp_a} operators{saved_str}."
        )

    # =========================================================================
    # 2. Efficiency % and Balancing Delay % Comparison
    # =========================================================================
    eff_diff = eff_a - eff_b
    if abs(eff_diff) < 0.15:
        sentences.append(
            f"Both methods deliver comparable line efficiency at {eff_a:.1f}% vs {eff_b:.1f}% (balancing delay of {delay_a:.1f}% vs {delay_b:.1f}%)."
        )
    elif eff_a > eff_b:
        sentences.append(
            f"Method A achieves higher line efficiency at {eff_a:.1f}% (balancing delay of {delay_a:.1f}%) compared to Method B at {eff_b:.1f}% (balancing delay of {delay_b:.1f}%)."
        )
    else:
        sentences.append(
            f"Method B achieves higher line efficiency at {eff_b:.1f}% (balancing delay of {delay_b:.1f}%) compared to Method A at {eff_a:.1f}% (balancing delay of {delay_a:.1f}%)."
        )

    # =========================================================================
    # 3. Stations to Flag for Method Study
    # =========================================================================
    # Method B: operations flagged "Above UCL — review"
    flagged_b_ops = []
    rows_b = method_b.get("rows", [])
    for r in rows_b:
        status = str(r.get("Status", ""))
        if "Above UCL" in status or "review" in status.lower():
            op_id = r.get("Serial/Id", "")
            op_name = r.get("Operations", "")
            flagged_b_ops.append(f"WS {r.get('Composite Operations')} [Op {op_id}: {op_name}]")

    # Method A: operations split (M/P >= 2)
    split_a_ops = []
    rows_a = method_a.get("rows", [])
    for r in rows_a:
        try:
            mp_val = int(r.get("M/P", 1))
        except (ValueError, TypeError):
            mp_val = 1
        if mp_val > 1:
            op_id = r.get("Serial/Id", "")
            op_name = r.get("Operations", "")
            split_a_ops.append(f"WS {r.get('Composite Operations')} [Op {op_id}: {op_name} (M/P={mp_val})]")

    # Build Sentence 3 phrasing
    if flagged_b_ops and split_a_ops:
        b_list_str = ", ".join(flagged_b_ops[:3]) + (f" and {len(flagged_b_ops)-3} more" if len(flagged_b_ops) > 3 else "")
        a_list_str = ", ".join(split_a_ops[:3]) + (f" and {len(split_a_ops)-3} more" if len(split_a_ops) > 3 else "")
        sentences.append(
            f"For method study: Method B has {len(flagged_b_ops)} station(s) flagged above UCL ({b_list_str}), while Method A required manpower splitting on {len(split_a_ops)} station(s) ({a_list_str})."
        )
    elif flagged_b_ops and not split_a_ops:
        b_list_str = ", ".join(flagged_b_ops[:3]) + (f" and {len(flagged_b_ops)-3} more" if len(flagged_b_ops) > 3 else "")
        sentences.append(
            f"For method study: Method B has {len(flagged_b_ops)} station(s) flagged above UCL ({b_list_str}), whereas no operations required manpower splitting in Method A."
        )
    elif not flagged_b_ops and split_a_ops:
        a_list_str = ", ".join(split_a_ops[:3]) + (f" and {len(split_a_ops)-3} more" if len(split_a_ops) > 3 else "")
        sentences.append(
            f"For method study: No operations required review in Method B, while Method A required manpower splitting on {len(split_a_ops)} station(s) ({a_list_str})."
        )
    else:
        sentences.append(
            "For method study: No operations required review in Method B, and no operations required manpower splitting in Method A."
        )

    # =========================================================================
    # 4. Overall Takeaway (Adaptive conclusion based on real numbers)
    # =========================================================================
    if mp_a < mp_b and eff_a >= eff_b:
        sentences.append(
            f"Overall, Method A is clearly preferable, achieving the target output with {mp_b - mp_a} fewer operators and superior efficiency ({eff_a:.1f}%)."
        )
    elif mp_b < mp_a and eff_b >= eff_a:
        sentences.append(
            f"Overall, Method B is clearly preferable, achieving the target output with {mp_a - mp_b} fewer operators and superior efficiency ({eff_b:.1f}%)."
        )
    elif mp_a < mp_b and eff_b > eff_a:
        sentences.append(
            f"Overall, results present a trade-off: Method A minimizes labor headcount ({mp_a} vs {mp_b} operators), while Method B provides higher balance efficiency ({eff_b:.1f}% vs {eff_a:.1f}%)."
        )
    elif mp_b < mp_a and eff_a > eff_b:
        sentences.append(
            f"Overall, results present a trade-off: Method B minimizes labor headcount ({mp_b} vs {mp_a} operators), while Method A provides higher balance efficiency ({eff_a:.1f}% vs {eff_b:.1f}%)."
        )
    elif mp_a == mp_b:
        if eff_a > eff_b + 1.0:
            sentences.append(
                f"Overall, Method A is preferable at equal headcount ({mp_a} operators) due to higher line efficiency ({eff_a:.1f}% vs {eff_b:.1f}%)."
            )
        elif eff_b > eff_a + 1.0:
            sentences.append(
                f"Overall, Method B is preferable at equal headcount ({mp_b} operators) due to higher line efficiency ({eff_b:.1f}% vs {eff_a:.1f}%)."
            )
        else:
            sentences.append(
                f"Overall, both methods yield closely matched results ({mp_a} operators, ~{eff_a:.1f}% efficiency); Method A offers strict pacing while Method B pinpoints candidate stations for pitch refinement."
            )

    return sentences
