from ablation.harness import verdict_for


def test_no_skill_can_reach_evict_at_any_similarity() -> None:
    for similarity in (0.0, 0.5, 0.9, 0.98, 1.0):
        assert verdict_for(similarity, memory_type="skill") != "evict"


def test_profile_reaches_evict_at_high_similarity() -> None:
    assert verdict_for(1.0, memory_type="profile") == "evict"


def test_thin_evidence_cannot_reach_evict_for_any_type() -> None:
    for memory_type in (None, "skill", "profile", "episode"):
        for similarity in (0.0, 0.5, 0.9, 0.98, 1.0):
            assert verdict_for(
                similarity, memory_type=memory_type, probes_tested=2
            ) != "evict"
