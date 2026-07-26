"""Tests for inter-model agreement metrics (RQ1 instrumentation)."""

from backend.agreement import compute_agreement, CONSENSUS_THRESHOLD


LABELS = {
    "Response A": "model-a",
    "Response B": "model-b",
    "Response C": "model-c",
    "Response D": "model-d",
}


def _ranking(model, order):
    return {"model": model, "parsed_ranking": order, "error": None}


class TestComputeAgreement:
    def test_perfect_agreement_is_consensus(self):
        # All four models rank identically; top pick (A) belongs to model-a,
        # so model-a's self-excluded vote goes to B — 3/4 still vote A.
        order = ["Response A", "Response B", "Response C", "Response D"]
        results = [_ranking(m, list(order)) for m in LABELS.values()]
        agreement = compute_agreement(results, LABELS)

        assert agreement is not None
        assert agreement["kendalls_w"] == 1.0
        assert agreement["mean_pairwise_tau"] == 1.0
        assert agreement["top1_agreement"] == 0.75
        assert agreement["top1_label"] == "Response A"
        assert agreement["council_state"] == "consensus"
        assert agreement["n_rankers"] == 4
        assert agreement["n_complete_rankings"] == 4

    def test_total_disagreement_is_divided(self):
        # Every model votes for a different top response.
        results = [
            _ranking("model-a", ["Response B", "Response C", "Response D", "Response A"]),
            _ranking("model-b", ["Response C", "Response D", "Response A", "Response B"]),
            _ranking("model-c", ["Response D", "Response A", "Response B", "Response C"]),
            _ranking("model-d", ["Response A", "Response B", "Response C", "Response D"]),
        ]
        agreement = compute_agreement(results, LABELS)

        assert agreement is not None
        assert agreement["top1_agreement"] == 0.25
        assert agreement["council_state"] == "divided"
        assert agreement["top1_entropy"] == 1.0
        # Latin-square rankings: rank sums identical => zero concordance
        assert agreement["kendalls_w"] == 0.0

    def test_self_vote_excluded_from_top1(self):
        # model-a ranks itself first; its effective vote is its second choice.
        results = [
            _ranking("model-a", ["Response A", "Response B", "Response C", "Response D"]),
            _ranking("model-b", ["Response A", "Response B", "Response C", "Response D"]),
            _ranking("model-c", ["Response A", "Response B", "Response C", "Response D"]),
            _ranking("model-d", ["Response A", "Response B", "Response C", "Response D"]),
        ]
        agreement = compute_agreement(results, LABELS)
        assert agreement["top1_votes"] == {"Response A": 3, "Response B": 1}

    def test_incomplete_rankings_excluded_from_w_but_counted_for_top1(self):
        results = [
            _ranking("model-a", ["Response B", "Response C", "Response D", "Response A"]),
            # model-b's top pick is its own response, so its vote falls to C
            _ranking("model-b", ["Response B", "Response C", "Response D", "Response A"]),
            _ranking("model-c", ["Response B"]),  # truncated/malformed ranking
        ]
        agreement = compute_agreement(results, LABELS)
        assert agreement["n_complete_rankings"] == 2
        assert agreement["n_rankers"] == 3
        assert agreement["top1_votes"] == {"Response B": 2, "Response C": 1}
        assert agreement["top1_agreement"] == 0.6667
        assert agreement["council_state"] == "divided"

    def test_errored_rankers_ignored(self):
        results = [
            _ranking("model-a", ["Response B", "Response A", "Response C", "Response D"]),
            _ranking("model-b", ["Response B", "Response A", "Response C", "Response D"]),
            {"model": "model-c", "parsed_ranking": [], "error": True},
        ]
        agreement = compute_agreement(results, LABELS)
        assert agreement is not None
        assert agreement["n_rankers"] == 2

    def test_returns_none_when_undefined(self):
        assert compute_agreement([], LABELS) is None
        assert compute_agreement([_ranking("model-a", ["Response A"])], LABELS) is None
        assert compute_agreement(
            [_ranking("model-a", ["Response A", "Response B"])],
            {"Response A": "model-a"},
        ) is None

    def test_threshold_boundary(self):
        # Exactly at threshold (3/4 = 0.75) counts as consensus.
        assert CONSENSUS_THRESHOLD == 0.75
        results = [
            _ranking("model-a", ["Response B", "Response A", "Response C", "Response D"]),
            _ranking("model-b", ["Response C", "Response A", "Response B", "Response D"]),
            _ranking("model-c", ["Response B", "Response A", "Response D", "Response C"]),
            _ranking("model-d", ["Response B", "Response A", "Response C", "Response D"]),
        ]
        agreement = compute_agreement(results, LABELS)
        assert agreement["top1_agreement"] == 0.75
        assert agreement["council_state"] == "consensus"
