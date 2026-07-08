"""Pure tournament bracket logic - no Flask, no DB. Testable in isolation."""

import random

GROUP_ROUND_ORDER = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]
GROUP_ROUNDS = [1, 1, 2, 2, 3, 3]


def round_robin_matches(pair_ids):
    """4 pair ids -> 6 (round_number, pair_a_id, pair_b_id) tuples, 3 rounds of 2 parallel matches."""
    if len(pair_ids) != 4:
        raise ValueError("groups must have exactly 4 pairs")
    return [
        (round_no, pair_ids[a], pair_ids[b])
        for (a, b), round_no in zip(GROUP_ROUND_ORDER, GROUP_ROUNDS)
    ]


def run_draw(pair_ids):
    """Shuffle pairs, assign group numbers, generate all group-stage matches.

    Returns (group_assignments, matches) where:
      group_assignments = {pair_id: group_number}
      matches = [{"stage": "group", "group_number": n, "round_number": r,
                  "pair_a_id": ..., "pair_b_id": ...}, ...]
    """
    if len(pair_ids) % 4 != 0:
        raise ValueError("pair count must be a multiple of 4")
    shuffled = list(pair_ids)
    random.shuffle(shuffled)
    groups_count = len(shuffled) // 4

    group_assignments = {}
    matches = []
    idx = 0
    for g in range(groups_count):
        group_number = g + 1
        group_pairs = shuffled[g * 4:(g + 1) * 4]
        for pid in group_pairs:
            group_assignments[pid] = group_number
        for round_no, a, b in round_robin_matches(group_pairs):
            matches.append({
                "stage": "group",
                "group_number": group_number,
                "round_number": round_no,
                "match_index": idx,
                "pair_a_id": a,
                "pair_b_id": b,
            })
            idx += 1
    return group_assignments, matches


def compute_group_standings(pair_ids, group_matches):
    """pair_ids: pairs in one group. group_matches: completed matches for that group
    (each with pair_a_id, pair_b_id, score_a, score_b, winner_pair_id).

    Returns list of pair_ids ranked best-first: wins desc, game_diff desc, games_won desc.
    Ties beyond that keep the input order (deterministic, not manually resolved).
    """
    stats = {pid: {"wins": 0, "games_won": 0, "games_lost": 0} for pid in pair_ids}
    for m in group_matches:
        if m.get("winner_pair_id") is None:
            continue
        a, b = m["pair_a_id"], m["pair_b_id"]
        sa, sb = m["score_a"], m["score_b"]
        if a in stats:
            stats[a]["games_won"] += sa
            stats[a]["games_lost"] += sb
            if m["winner_pair_id"] == a:
                stats[a]["wins"] += 1
        if b in stats:
            stats[b]["games_won"] += sb
            stats[b]["games_lost"] += sa
            if m["winner_pair_id"] == b:
                stats[b]["wins"] += 1

    def sort_key(pid):
        s = stats[pid]
        diff = s["games_won"] - s["games_lost"]
        return (-s["wins"], -diff, -s["games_won"])

    ranked = sorted(pair_ids, key=sort_key)
    return ranked, stats


def group_qualifiers(groups_count, standings_by_group):
    """standings_by_group: {group_number: ranked_pair_ids (best first)}.
    Returns ordered list [(group_number, rank, pair_id), ...] for rank 1 and 2 of every group,
    ordered by group number then rank.
    """
    qualifiers = []
    for g in range(1, groups_count + 1):
        ranked = standings_by_group[g]
        qualifiers.append((g, 1, ranked[0]))
        qualifiers.append((g, 2, ranked[1]))
    return qualifiers


def _qualifier_pair_id(qualifiers, group_number, rank):
    for g, r, pid in qualifiers:
        if g == group_number and r == rank:
            return pid
    raise ValueError(f"no qualifier for group {group_number} rank {rank}")


def generate_next_stage(tournament_pairs_count, groups_count, current_stage, standings_by_group=None,
                         stage_winner_ids_in_order=None):
    """Compute the matches for the stage that follows `current_stage`.

    - current_stage == "group": needs standings_by_group ({group_number: ranked_pair_ids}).
      Returns (next_stage_name, matches) where matches is a list of
      {"pair_a_id", "pair_b_id"} dicts (no scores yet).
    - current_stage in ("quarterfinal", "semifinal"): needs stage_winner_ids_in_order
      (winners in the same order the matches were created). Pairs consecutive winners.
    - current_stage == "final": returns (None, []) - tournament is complete.
    """
    if current_stage == "group":
        qualifiers = group_qualifiers(groups_count, standings_by_group)
        if groups_count == 2:
            return "semifinal", _with_match_index([
                {"pair_a_id": _qualifier_pair_id(qualifiers, 1, 1), "pair_b_id": _qualifier_pair_id(qualifiers, 2, 2)},
                {"pair_a_id": _qualifier_pair_id(qualifiers, 2, 1), "pair_b_id": _qualifier_pair_id(qualifiers, 1, 2)},
            ])
        if groups_count == 4:
            return "quarterfinal", _with_match_index([
                {"pair_a_id": _qualifier_pair_id(qualifiers, 1, 1), "pair_b_id": _qualifier_pair_id(qualifiers, 3, 2)},
                {"pair_a_id": _qualifier_pair_id(qualifiers, 3, 1), "pair_b_id": _qualifier_pair_id(qualifiers, 1, 2)},
                {"pair_a_id": _qualifier_pair_id(qualifiers, 2, 1), "pair_b_id": _qualifier_pair_id(qualifiers, 4, 2)},
                {"pair_a_id": _qualifier_pair_id(qualifiers, 4, 1), "pair_b_id": _qualifier_pair_id(qualifiers, 2, 2)},
            ])
        raise ValueError(f"unsupported groups_count {groups_count}")

    if current_stage == "quarterfinal":
        w = stage_winner_ids_in_order
        return "semifinal", _with_match_index([
            {"pair_a_id": w[0], "pair_b_id": w[1]},
            {"pair_a_id": w[2], "pair_b_id": w[3]},
        ])

    if current_stage == "semifinal":
        w = stage_winner_ids_in_order
        return "final", _with_match_index([
            {"pair_a_id": w[0], "pair_b_id": w[1]},
        ])

    if current_stage == "final":
        return None, []

    raise ValueError(f"unknown stage {current_stage}")


def _with_match_index(matches):
    for i, m in enumerate(matches):
        m["match_index"] = i
    return matches


def score_winner(pair_a_id, pair_b_id, score_a, score_b):
    if score_a == score_b:
        raise ValueError("no ties allowed - scores must differ")
    return pair_a_id if score_a > score_b else pair_b_id
