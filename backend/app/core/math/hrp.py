"""
Hierarchical Risk Parity (Lopez de Prado, 2016).

HRP allocates capital across strategies (or markets) by:
1. Build correlation matrix from P&L return series
2. Hierarchical clustering (Ward linkage)
3. Quasi-diagonalize covariance matrix
4. Recursive bisection (risk parity within clusters)

Advantages over Markowitz:
  - Does not require matrix inversion (more numerically stable)
  - Robust to estimation error in expected returns
  - Works well with small samples (e.g. 30 days of strategy P&L)

Reference: López de Prado, M. (2016). Building Diversified Portfolios
that Outperform Out of Sample.
"""
from __future__ import annotations


import numpy as np

try:
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def hrp_weights(
    returns_matrix: np.ndarray,  # Shape: (n_periods, n_assets)
    min_periods: int = 10,
) -> list[float]:
    """
    Compute HRP weights given a matrix of asset P&L returns.

    Args:
        returns_matrix: (T, N) array where T=periods, N=assets (strategies)
        min_periods: Minimum periods required, else returns equal weights

    Returns:
        List of N weights summing to 1.0
    """
    n_periods, n_assets = returns_matrix.shape

    if n_assets == 1:
        return [1.0]

    if n_periods < min_periods or not SCIPY_AVAILABLE:
        return [1.0 / n_assets] * n_assets

    # Compute covariance and correlation matrices
    cov = np.cov(returns_matrix.T)
    std = np.sqrt(np.diag(cov))
    std = np.where(std == 0, 1e-10, std)  # avoid div by zero
    corr = cov / np.outer(std, std)
    corr = np.clip(corr, -1, 1)

    # Step 1: Distance matrix from correlation
    dist = np.sqrt((1 - corr) / 2)
    dist = np.clip(dist, 0, 1)

    # Step 2: Hierarchical clustering
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="ward")
    sort_ix = _get_quasi_diag(link, n_assets)

    # Step 3: Quasi-diagonalize
    sorted_cov = cov[np.ix_(sort_ix, sort_ix)]

    # Step 4: Recursive bisection
    weights = _recursive_bisection(sorted_cov, list(range(n_assets)))

    # Map back to original order
    result = [0.0] * n_assets
    for i, orig_idx in enumerate(sort_ix):
        result[orig_idx] = weights[i]

    return result


def _get_quasi_diag(link: np.ndarray, n: int) -> list[int]:
    """Get leaf order from hierarchical clustering (quasi-diagonalization)."""
    link = link.astype(int)
    sort_ix = _get_leaves(link, n, int(link[-1, 0]), int(link[-1, 1]))
    return sort_ix


def _get_leaves(link: np.ndarray, n: int, left: int, right: int) -> list[int]:
    """Recursively get leaf nodes in order."""
    if left < n:
        left_leaves = [left]
    else:
        left_leaves = _get_leaves(link, n, int(link[left - n, 0]), int(link[left - n, 1]))
    if right < n:
        right_leaves = [right]
    else:
        right_leaves = _get_leaves(link, n, int(link[right - n, 0]), int(link[right - n, 1]))
    return left_leaves + right_leaves


def _cluster_var(cov: np.ndarray, indices: list[int]) -> float:
    """Variance of an equal-weight portfolio of the given indices."""
    sub_cov = cov[np.ix_(indices, indices)]
    n = len(indices)
    w = np.array([1.0 / n] * n)
    return float(w @ sub_cov @ w)


def _recursive_bisection(cov: np.ndarray, indices: list[int]) -> list[float]:
    """Allocate weights via recursive bisection."""
    weights = [1.0] * len(indices)

    def _bisect(cluster_items: list[int]) -> None:
        if len(cluster_items) <= 1:
            return

        # Split into two halves
        split = len(cluster_items) // 2
        left = cluster_items[:split]
        right = cluster_items[split:]

        var_left = _cluster_var(cov, left)
        var_right = _cluster_var(cov, right)

        total_var = var_left + var_right
        if total_var == 0:
            alpha = 0.5
        else:
            alpha = 1 - var_left / total_var  # Allocate inverse of variance

        for idx in left:
            weights[idx] *= alpha
        for idx in right:
            weights[idx] *= (1 - alpha)

        _bisect(left)
        _bisect(right)

    _bisect(list(range(len(indices))))

    total = sum(weights)
    return [w / total for w in weights] if total > 0 else [1.0 / len(indices)] * len(indices)
