"""Column-generation helpers extracted from column_generation.py (audit Q4).

These are pure-data utility functions used by the CG solver: pattern
seeding, cost computation, and diversified initialisation.
"""

def _profs_iter_with_groups(profs: dict,
                             group_assignments: list | None
                             ) -> dict[str, list[tuple[str, str]]]:
    """Build a per-teacher iterator over (class_name, subject) pairs
    that includes BOTH the regular class entries from
    `profs[p].classi` AND the StudyGroup-targeted entries from
    `group_assignments`. Returns dict[teacher_name -> list[(cl, s)]].

    Task C3: CG patterns for group teachers were silently empty
    because their `classi` is empty (the group hours arrive via
    `group_assignments` and are augmented to the triples list inside
    cv2.solve_phase_a only). Without this helper, _seed_patterns
    skipped group teachers entirely.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for p in sorted(profs.keys()):
        pairs: list[tuple[str, str]] = []
        for cl, sub_dict in (profs[p]["classi"]).items():
            for subj in sub_dict.keys():
                pairs.append((cl, subj))
        out[p] = pairs
    for ga in (group_assignments or []):
        t = ga["teacher_name"]
        cl = ga["group_name"]
        s = ga["subject"]
        pair = (cl, s)
        existing = out.setdefault(t, [])
        if pair not in existing:
            existing.append(pair)
    return out


def _seed_patterns(profs: dict, dc_value: dict, max_per_teacher: int = 3,
                   locks: set | None = None,
                   group_assignments: list | None = None,
                   ) -> dict[str, list[dict]]:
    """Build a small initial pattern catalog from `dc_value` (Phase-A
    output), one or more "shifted" patterns per teacher.

    A pattern is a dict {(p, cl, subj, day, hour): 0/1}.

    The seed strategy: for each teacher with phase-A counts, place
    the lessons greedily into the first available (day, hour) slots
    that don't conflict with previously-placed lessons. Then we
    rotate the start hour by 1, 2, 3 to obtain `max_per_teacher`
    deterministic variants.

    `locks` (optional): a set of (p, cl, subj, day, hour) tuples
    that MUST appear in every generated pattern. They are pre-placed
    before the greedy fill so the rest of the schedule wraps around
    them. Callers are responsible for keeping `dc_value` consistent
    with the locks (i.e. day_count >= n_locked_in_day).
    """
    locks = locks or set()
    locks_by_teacher: dict[str, list[tuple]] = {}
    for (p, cl, s, d, h) in locks:
        locks_by_teacher.setdefault(p, []).append((cl, s, d, h))

    out: dict[str, list[dict]] = {}
    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    profs_list = sorted(pairs_by_t.keys())
    for p in profs_list:
        # IMPORTANT: include the DAY in the triple. Earlier versions
        # carried only (p, cl, subj, count) and tried to rediscover
        # the day inside the placement loop -- but two distinct days
        # with non-zero dc_value produced TWO identical entries that
        # both placed in the first non-zero day, generating "extra
        # hours" of the same cattedra in one day. Now each
        # (cattedra, day) pair gets exactly one greedy placement
        # for `count` hours.
        triples = [(p, cl, subj, d, dc_value.get((p, cl, subj, d), 0))
                    for (cl, subj) in pairs_by_t[p]
                    for d in DAYS]
        triples = [t for t in triples if t[4] > 0]
        if not triples:
            out[p] = []
            continue
        patterns: list[dict] = []
        for offset in range(max_per_teacher):
            pat: dict = {}
            occupied_t: set = set()       # (p, d, h)
            occupied_c: set = set()       # (cl, d, h)
            # Pre-place the teacher's locks. The greedy fill below
            # treats those slots as occupied.
            for (cl_l, s_l, d_l, h_l) in locks_by_teacher.get(p, []):
                pat[(p, cl_l, s_l, d_l, h_l)] = 1
                occupied_t.add((p, d_l, h_l))
                occupied_c.add((cl_l, d_l, h_l))
            for (pp, cl, subj, d, hours_to_place) in triples:
                # Subtract any locked hours already in the pattern for
                # this triple-day so we don't double-count.
                already = sum(
                    1 for (cl_l, s_l, d_l, _h_l)
                    in locks_by_teacher.get(p, [])
                    if cl_l == cl and s_l == subj and d_l == d
                )
                placed = already
                for h_idx in range(len(HOURS)):
                    # Check BEFORE placement: if already at quota,
                    # don't even try to add more (avoids the
                    # off-by-one where placed==quota lets one extra
                    # hour slip through before the post-add break).
                    if placed >= hours_to_place:
                        break
                    h = HOURS[(h_idx + offset) % len(HOURS)]
                    if (pp, d, h) in occupied_t or (cl, d, h) in occupied_c:
                        continue
                    pat[(pp, cl, subj, d, h)] = 1
                    occupied_t.add((pp, d, h))
                    occupied_c.add((cl, d, h))
                    placed += 1
            if pat:
                patterns.append(pat)
        out[p] = patterns
    return out


