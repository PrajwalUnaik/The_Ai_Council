"""Inter-model agreement metrics computed from Stage 2 peer rankings.

Research instrumentation (RQ1): quantifies how much the council models agree
in their peer rankings so that agreement can be (a) validated as a predictor
of answer quality and (b) surfaced in the adaptive interface (RQ2/RQ3).

All metrics are computed from the `parsed_ranking` lists produced by
`stage2_collect_rankings` and the `label_to_model` mapping.
"""

import math
from collections import Counter
from typing import Any, Dict, List, Optional

# A run is labelled "consensus" when at least this fraction of rankers agree
# on the same top-ranked response (self-votes excluded). Otherwise "divided".
CONSENSUS_THRESHOLD = 0.75


def _complete_rankings(
    stage2_results: List[Dict[str, Any]],
    labels: List[str],
) -> List[Dict[str, Any]]:
    """Filter to rankers whose parsed ranking is a complete permutation of labels."""
    label_set = set(labels)
    complete = []
    for result in stage2_results:
        if result.get("error"):
            continue
        parsed = result.get("parsed_ranking") or []
        if len(parsed) == len(label_set) and set(parsed) == label_set:
            complete.append(result)
    return complete


def _kendalls_w(rank_matrix: List[List[int]]) -> Optional[float]:
    """Kendall's coefficient of concordance for m complete rankings of n items.

    rank_matrix[rater][item] = 1-based rank assigned by rater to item.
    Returns W in [0, 1], or None if undefined (fewer than 2 raters/items).
    """
    m = len(rank_matrix)
    if m < 2:
        return None
    n = len(rank_matrix[0])
    if n < 2:
        return None

    # Rank sums per item
    rank_sums = [sum(rater[j] for rater in rank_matrix) for j in range(n)]
    mean_sum = sum(rank_sums) / n
    s = sum((r - mean_sum) ** 2 for r in rank_sums)
    denominator = (m ** 2) * (n ** 3 - n) / 12.0
    if denominator == 0:
        return None
    return round(s / denominator, 4)


def _kendall_tau(order_a: List[str], order_b: List[str]) -> Optional[float]:
    """Kendall's tau-a between two complete rankings (permutations of same labels)."""
    n = len(order_a)
    if n < 2 or set(order_a) != set(order_b):
        return None
    pos_b = {label: i for i, label in enumerate(order_b)}
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            # order_a places order_a[i] above order_a[j]
            if pos_b[order_a[i]] < pos_b[order_a[j]]:
                concordant += 1
            else:
                discordant += 1
    total_pairs = n * (n - 1) / 2
    return (concordant - discordant) / total_pairs


def _mean_pairwise_tau(rankings: List[List[str]]) -> Optional[float]:
    """Average Kendall's tau across all rater pairs."""
    taus = []
    for i in range(len(rankings)):
        for j in range(i + 1, len(rankings)):
            tau = _kendall_tau(rankings[i], rankings[j])
            if tau is not None:
                taus.append(tau)
    if not taus:
        return None
    return round(sum(taus) / len(taus), 4)


def _top1_votes(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str],
) -> List[str]:
    """Each ranker's top pick, excluding its own (anonymised) response.

    A model cannot meaningfully "agree" by voting for itself, so when a
    ranker's top-ranked label maps back to its own model, we take its next
    highest pick instead.
    """
    model_to_label = {model: label for label, model in label_to_model.items()}
    votes = []
    for result in stage2_results:
        if result.get("error"):
            continue
        parsed = result.get("parsed_ranking") or []
        own_label = model_to_label.get(result.get("model"))
        for label in parsed:
            if label != own_label:
                votes.append(label)
                break
    return votes


def _normalized_entropy(votes: List[str], n_items: int) -> Optional[float]:
    """Shannon entropy of the top-1 vote distribution, normalised to [0, 1]."""
    if not votes or n_items < 2:
        return None
    counts = Counter(votes)
    total = len(votes)
    entropy = -sum(
        (c / total) * math.log2(c / total)
        for c in counts.values()
    )
    max_entropy = math.log2(n_items)
    if max_entropy == 0:
        return None
    return round(min(entropy / max_entropy, 1.0), 4)


def compute_agreement(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Compute inter-model agreement metrics for one council run.

    Returns None when fewer than 2 valid rankings exist (agreement undefined).
    """
    if not stage2_results or not label_to_model or len(label_to_model) < 2:
        return None

    labels = list(label_to_model.keys())
    complete = _complete_rankings(stage2_results, labels)

    # --- Full-ranking concordance (Kendall's W, mean pairwise tau) ---
    kendalls_w = None
    mean_tau = None
    if len(complete) >= 2:
        label_index = {label: i for i, label in enumerate(labels)}
        rank_matrix = []
        orders = []
        for result in complete:
            parsed = result["parsed_ranking"]
            ranks = [0] * len(labels)
            for position, label in enumerate(parsed, start=1):
                ranks[label_index[label]] = position
            rank_matrix.append(ranks)
            orders.append(parsed)
        kendalls_w = _kendalls_w(rank_matrix)
        mean_tau = _mean_pairwise_tau(orders)

    # --- Top-1 agreement (self-votes excluded) ---
    votes = _top1_votes(stage2_results, label_to_model)
    if len(votes) < 2:
        return None

    vote_counts = Counter(votes)
    modal_label, modal_count = vote_counts.most_common(1)[0]
    top1_agreement = round(modal_count / len(votes), 4)
    top1_entropy = _normalized_entropy(votes, len(labels))

    council_state = "consensus" if top1_agreement >= CONSENSUS_THRESHOLD else "divided"

    return {
        "kendalls_w": kendalls_w,
        "mean_pairwise_tau": mean_tau,
        "top1_agreement": top1_agreement,
        "top1_label": modal_label,
        "top1_model": label_to_model.get(modal_label),
        "top1_votes": dict(vote_counts),
        "top1_entropy": top1_entropy,
        "council_state": council_state,
        "consensus_threshold": CONSENSUS_THRESHOLD,
        "n_rankers": len(votes),
        "n_complete_rankings": len(complete),
        "n_items": len(labels),
    }
