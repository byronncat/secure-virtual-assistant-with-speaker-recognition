"""
metrics.py
==========
Standard metrics for Speaker Verification:
  - EER     (Equal Error Rate)
  - minDCF  (minimum Detection Cost Function, following the NIST SRE standard)

For the Speaker Identification (closed-set) task, this module also provides
accuracy / top-k accuracy for train.py.
"""

import numpy as np
from sklearn.metrics import roc_curve


def compute_eer(labels, scores):
    """
    labels: 0/1 array (1 = target/same speaker, 0 = nontarget)
    scores: similarity-score array (higher values indicate greater similarity,
        e.g. cosine similarity)
    Returns (eer, threshold_at_eer)
    """
    fpr, tpr, thresholds = roc_curve(labels, scores, pos_label=1)
    fnr = 1 - tpr
    # Find the point where FPR and FNR are closest.
    idx = np.nanargmin(np.abs(fnr - fpr))
    eer = (fpr[idx] + fnr[idx]) / 2
    eer_threshold = thresholds[idx]
    return float(eer), float(eer_threshold)


def compute_min_dcf(labels, scores, p_target=0.01, c_miss=1, c_fa=1):
    """
    Calculate minDCF using the NIST formula:
        DCF(theta) = c_miss * p_target * P_miss(theta)
                   + c_fa   * (1 - p_target) * P_fa(theta)
        minDCF = min_theta DCF(theta), usually normalized.
    """
    fpr, tpr, thresholds = roc_curve(labels, scores, pos_label=1)
    fnr = 1 - tpr

    dcf = c_miss * p_target * fnr + c_fa * (1 - p_target) * fpr
    min_idx = np.argmin(dcf)
    min_dcf = dcf[min_idx]

    dcf_default = min(c_miss * p_target, c_fa * (1 - p_target))
    min_dcf_norm = min_dcf / dcf_default
    return float(min_dcf), float(min_dcf_norm), float(thresholds[min_idx])


def top_k_accuracy(logits, labels, k=1):
    """Compute top-k accuracy for Speaker Identification (closed-set)."""
    topk = logits.topk(k, dim=-1).indices
    correct = topk.eq(labels.unsqueeze(-1)).any(dim=-1)
    return correct.float().mean().item()
