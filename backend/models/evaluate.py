"""
evaluate.py
===========
Standalone evaluation for a trained ECAPA-TDNN speaker-recognition model.

Evaluates both components required by the project:
  * Speaker verification (SV)    -> EER, minDCF     on verification_trials.csv
                                     (closed-set pairwise trials; used to gate
                                     "important" actions)
  * Speaker identification (SID) -> open-set identification on
                                     open_set_identification_trials.csv, using
                                     centroids built from train.csv/enrollment.
                                     Each query is either KNOWN (its speaker is
                                     enrolled) or UNKNOWN (its speaker is not).
                                     A query is accepted, and assigned to its
                                     best-matching enrolled speaker, only if the
                                     best similarity score clears the rejection
                                     threshold; otherwise it is predicted UNKNOWN.

The open-set rejection threshold is ALWAYS determined automatically from
val.csv (never from open_set_identification_trials.csv): every val.csv
utterance is scored against every enrolled-speaker centroid, its score
against its own true speaker is a genuine trial and its scores against every
other centroid are impostor trials, and the minDCF-optimal threshold over
those genuine/impostor scores is fixed and reused unchanged for the final
open-set evaluation. Set evaluation.threshold in the config to override this
automatic search with a fixed value instead.

Usage:
    python evaluate.py --config configs/ecapa_config.yaml
    python evaluate.py --config configs/ecapa_config.yaml --checkpoint checkpoints/best_model.pt

    # Skip one evaluation during development:
    python evaluate.py --config configs/ecapa_config.yaml --skip-identification
    python evaluate.py --config configs/ecapa_config.yaml --skip-verification
"""

import argparse
import logging
import os

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import yaml
from torch.utils.tensorboard import SummaryWriter
from tqdm.auto import tqdm

from dataset import SpeakerDataset
from metrics import compute_eer, compute_min_dcf
from model import ECAPAModel

LOGGER = logging.getLogger("speaker_evaluation")


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def build_encoder(model_cfg):
    return ECAPAModel(
        input_size=model_cfg["input_size"],
        lin_neurons=model_cfg["lin_neurons"],
        channels=model_cfg["channels"],
        kernel_sizes=model_cfg["kernel_sizes"],
        dilations=model_cfg["dilations"],
        attention_channels=model_cfg["attention_channels"],
    )


def load_checkpoint(encoder, checkpoint_path, device):
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    if "encoder" not in checkpoint:
        raise ValueError(
            f"Checkpoint does not contain encoder weights: {checkpoint_path}"
        )
    encoder.load_state_dict(checkpoint["encoder"])
    return checkpoint.get("epoch", "unknown")


def embed_path(encoder, feature_dataset, path, device):
    feats = feature_dataset.extract_features_full(path).unsqueeze(0).to(device)
    return F.normalize(encoder(feats), dim=-1).cpu()


# ---------------------------------------------------------------------------
# Speaker verification
# ---------------------------------------------------------------------------
def evaluate_verification(encoder, feature_dataset, trial_list, device, evaluation_cfg):
    trials = pd.read_csv(trial_list)
    required = {"enrollment_path", "test_path", "label"}
    if not required.issubset(trials.columns):
        raise ValueError(f"Trial list must contain columns: {sorted(required)}")
    if trials.empty:
        raise ValueError(f"Trial list is empty: {trial_list}")

    LOGGER.info("Extracting embeddings | trials=%d", len(trials))
    embeddings = {}
    encoder.eval()
    paths = pd.concat([trials["enrollment_path"], trials["test_path"]]).unique()
    with torch.no_grad():
        for path in tqdm(paths, desc="Embedding progress", unit="files"):
            embeddings[path] = embed_path(encoder, feature_dataset, path, device)

    scores = [
        float((embeddings[row.enrollment_path] * embeddings[row.test_path]).sum())
        for row in trials.itertuples(index=False)
    ]
    labels = trials["label"].to_numpy()
    eer, eer_threshold = compute_eer(labels, scores)
    min_dcf, normalized_min_dcf, dcf_threshold = compute_min_dcf(
        labels,
        scores,
        p_target=evaluation_cfg["dcf_p_target"],
        c_miss=evaluation_cfg["dcf_c_miss"],
        c_fa=evaluation_cfg["dcf_c_fa"],
    )
    return {
        "eer": eer,
        "eer_threshold": eer_threshold,
        "min_dcf": min_dcf,
        "normalized_min_dcf": normalized_min_dcf,
        "dcf_threshold": dcf_threshold,
    }


# ---------------------------------------------------------------------------
# Speaker identification
# ---------------------------------------------------------------------------
def build_speaker_centroids(encoder, feature_dataset, enrollment_list, device):
    """Average the (L2-normalized) embeddings of each enrolled speaker's
    enrollment utterances into a single centroid, mirroring the enrollment
    procedure used by the virtual assistant's speaker-management component.

    `enrollment_list` is train.csv: every training speaker is treated as a
    registered/enrolled speaker, and its training utterances are averaged
    into that speaker's centroid.
    """
    enrollment = pd.read_csv(enrollment_list)
    required = {"speaker_id", "file_path"}
    if not required.issubset(enrollment.columns):
        raise ValueError(f"Enrollment list must contain columns: {sorted(required)}")
    if enrollment.empty:
        raise ValueError(f"Enrollment list is empty: {enrollment_list}")

    LOGGER.info(
        "Building speaker centroids | speakers=%d | enrollment_utterances=%d",
        enrollment["speaker_id"].nunique(),
        len(enrollment),
    )
    encoder.eval()
    centroids = {}
    with torch.no_grad():
        for speaker_id, group in tqdm(
            enrollment.groupby("speaker_id"),
            total=enrollment["speaker_id"].nunique(),
            desc="Centroids progress",
            unit="speakers",
        ):
            embeds = [
                embed_path(encoder, feature_dataset, path, device)
                for path in group["file_path"]
            ]
            centroid = torch.mean(torch.cat(embeds, dim=0), dim=0, keepdim=True)
            centroids[speaker_id] = F.normalize(centroid, dim=-1)
    return centroids


def score_val_trials(encoder, feature_dataset, val_list, centroids, device):
    """Score every val.csv utterance against every enrolled-speaker centroid.

    val.csv utterances belong to the same speakers as the enrollment set
    (train.csv, speaker-closed split). For every val.csv utterance we score
    it against every enrolled speaker's centroid: the score against its own
    true speaker forms a genuine trial, and the scores against every other
    enrolled speaker form impostor trials.

    This is the ONE piece of information ever taken from val.csv. Both the
    single auto-derived (minDCF) threshold and the multi-threshold sweep grid
    are built from this same (labels, scores) pair -- open_set_identification
    _trials.csv is never touched by any of this.
    """
    speaker_ids = list(centroids.keys())
    centroid_matrix = torch.cat([centroids[sid] for sid in speaker_ids], dim=0)

    val_queries = pd.read_csv(val_list)
    required = {"speaker_id", "file_path"}
    if not required.issubset(val_queries.columns):
        raise ValueError(f"val_list must contain columns: {sorted(required)}")
    if val_queries.empty:
        raise ValueError(f"val_list is empty: {val_list}")

    LOGGER.info(
        "Scoring val_list trials | val_utterances=%d | enrolled_speakers=%d",
        len(val_queries),
        len(speaker_ids),
    )

    labels, scores = [], []
    encoder.eval()
    with torch.no_grad():
        for row in tqdm(
            val_queries.itertuples(index=False),
            total=len(val_queries),
            desc="Val scoring progress",
            unit="files",
        ):
            if row.speaker_id not in centroids:
                # Should not happen given the speaker-closed train/val split.
                continue
            embedding = embed_path(encoder, feature_dataset, row.file_path, device)
            sims = (embedding @ centroid_matrix.T).squeeze(0).tolist()
            for sid, sim in zip(speaker_ids, sims):
                labels.append(1 if sid == row.speaker_id else 0)
                scores.append(sim)
    return labels, scores


def select_mindcf_threshold(labels, scores, dcf_cfg):
    """The single "recommended" operating point: minDCF-optimal threshold
    over the val_list genuine/impostor scores, using the same
    dcf_p_target/c_miss/c_fa cost weights as verification. For a secure
    voice assistant, c_fa should be set well above c_miss so this threshold
    is biased toward rejecting strangers over inconveniencing genuine users.
    """
    _, _, dcf_threshold = compute_min_dcf(
        labels,
        scores,
        p_target=dcf_cfg["dcf_p_target"],
        c_miss=dcf_cfg["dcf_c_miss"],
        c_fa=dcf_cfg["dcf_c_fa"],
    )
    LOGGER.info(
        "Open-set identification threshold (minDCF-optimal, auto from val_list): %.6f",
        dcf_threshold,
    )
    return dcf_threshold


def build_threshold_grid(scores, sweep_cfg, auto_threshold):
    """Build the list of thresholds to evaluate on identification_test_list,
    grounded ONLY in val_list's own score distribution -- never in the test
    list itself.

    - If sweep_cfg["values"] is a non-empty list, those exact thresholds are
      used (e.g. a set of candidate operating points picked by hand).
    - Otherwise, `num_thresholds` values are spaced evenly between the
      `percentile_range` percentiles of the val_list genuine+impostor score
      distribution, so the grid automatically covers the range where the
      scores actually live instead of arbitrary hardcoded numbers.

    The minDCF-optimal `auto_threshold` is always folded into the grid (and
    flagged as the recommended row in the resulting table), even if it
    doesn't land exactly on a generated grid point.
    """
    explicit_values = sweep_cfg.get("values")
    if explicit_values:
        grid = sorted({round(float(v), 6) for v in explicit_values})
    else:
        num_thresholds = int(sweep_cfg.get("num_thresholds", 15))
        low_pct, high_pct = sweep_cfg.get("percentile_range", [1, 99])
        scores_arr = np.asarray(scores, dtype=float)
        low = np.percentile(scores_arr, low_pct)
        high = np.percentile(scores_arr, high_pct)
        grid = sorted({round(v, 6) for v in np.linspace(low, high, num_thresholds)})

    if sweep_cfg.get("include_auto_threshold", True):
        auto_rounded = round(float(auto_threshold), 6)
        if auto_rounded not in grid:
            grid.append(auto_rounded)
            grid.sort()
    return grid


def score_identification_queries(
    encoder, feature_dataset, centroids, identification_test_list, device, max_k
):
    """Embed every identification_test_list query exactly once and record,
    per query, everything a threshold decision needs: whether it's genuine
    (KNOWN, speaker IS enrolled) or impostor (UNKNOWN, speaker is NOT
    enrolled), its best similarity score against any enrolled centroid, and
    its top-max_k ranked enrolled speakers.

    Scoring/ranking is threshold-independent, so this expensive embedding
    pass runs once regardless of how many thresholds are later evaluated --
    compute_identification_metrics() below just does cheap bookkeeping over
    these precomputed records for each threshold.
    """
    speaker_ids = list(centroids.keys())
    enrolled_set = set(speaker_ids)
    centroid_matrix = torch.cat([centroids[sid] for sid in speaker_ids], dim=0)

    identification_queries = pd.read_csv(identification_test_list)
    required = {"speaker_id", "file_path"}
    if not required.issubset(identification_queries.columns):
        raise ValueError(
            f"Identification test list must contain columns: {sorted(required)}"
        )
    if identification_queries.empty:
        raise ValueError(
            f"Identification test list is empty: {identification_test_list}"
        )

    LOGGER.info(
        "Embedding identification queries | test_utterances=%d | enrolled_speakers=%d",
        len(identification_queries),
        len(speaker_ids),
    )

    records = []
    encoder.eval()
    with torch.no_grad():
        for row in tqdm(
            identification_queries.itertuples(index=False),
            total=len(identification_queries),
            desc="Identification embedding progress",
            unit="files",
        ):
            is_genuine = row.speaker_id in enrolled_set  # KNOWN vs UNKNOWN
            embedding = embed_path(encoder, feature_dataset, row.file_path, device)
            scores = (embedding @ centroid_matrix.T).squeeze(0)
            top_indices = torch.topk(
                scores, k=min(max_k, len(speaker_ids))
            ).indices.tolist()
            records.append(
                {
                    "is_genuine": is_genuine,
                    "true_speaker": row.speaker_id,
                    "ranked": [speaker_ids[i] for i in top_indices],
                    "best_score": scores[top_indices[0]].item(),
                }
            )
    return records


def compute_identification_metrics(records, reject_threshold, top_k):
    """One row of the open-set identification table, for a single
    `reject_threshold`, computed from precomputed per-query `records` (see
    score_identification_queries). A query is accepted, and assigned to its
    best-matching enrolled speaker, only if its best similarity score clears
    `reject_threshold`; otherwise it is rejected, i.e. predicted UNKNOWN.
    """
    correct_at_k = {k: 0 for k in top_k}
    genuine_total = genuine_accepted = 0
    impostor_total = impostor_accepted = 0

    for rec in records:
        accepted = rec["best_score"] >= reject_threshold
        if rec["is_genuine"]:
            genuine_total += 1
            if accepted:
                genuine_accepted += 1
                for k in top_k:
                    if rec["true_speaker"] in rec["ranked"][:k]:
                        correct_at_k[k] += 1
            # rejected genuine (KNOWN) trials count as false rejects below.
        else:
            impostor_total += 1
            if accepted:
                # false accept: UNKNOWN voice wrongly matched to an enrolled speaker
                impostor_accepted += 1

    results = {
        "threshold": reject_threshold,
        "num_known_queries": genuine_total,
        "num_unknown_queries": impostor_total,
    }
    for k in top_k:
        results[f"top{k}_accuracy_given_accept"] = (
            correct_at_k[k] / genuine_accepted if genuine_accepted else 0.0
        )
    results["genuine_acceptance_rate"] = (
        genuine_accepted / genuine_total if genuine_total else 0.0
    )
    results["false_reject_rate"] = 1.0 - results["genuine_acceptance_rate"]
    if impostor_total:
        results["impostor_false_accept_rate"] = impostor_accepted / impostor_total
        results["impostor_correct_rejection_rate"] = (
            1.0 - results["impostor_false_accept_rate"]
        )
    else:
        results["impostor_false_accept_rate"] = 0.0
        results["impostor_correct_rejection_rate"] = 0.0
    # Overall open-set accuracy: genuine (KNOWN) correctly accepted AND top-1 correct.
    results["overall_top1_accuracy"] = (
        correct_at_k[top_k[0]] / genuine_total if genuine_total else 0.0
    )
    return results


def evaluate_identification_sweep(records, thresholds, top_k, auto_threshold=None):
    """Build the full threshold-sweep table: one row per threshold in
    `thresholds`, each computed cheaply from the already-embedded `records`.
    The row matching `auto_threshold` (the minDCF-optimal, val_list-derived
    threshold) is flagged via `recommended_auto_threshold` so it's easy to
    pick out in the saved table.
    """
    rows = []
    for reject_threshold in thresholds:
        row = compute_identification_metrics(records, reject_threshold, top_k)
        # Grid thresholds are rounded to 6 decimals (see build_threshold_grid),
        # so compare at that same precision rather than exact float equality.
        row["recommended_auto_threshold"] = (
            auto_threshold is not None and abs(reject_threshold - auto_threshold) < 1e-6
        )
        rows.append(row)
    columns = (
        ["threshold", "recommended_auto_threshold"]
        + [f"top{k}_accuracy_given_accept" for k in top_k]
        + [
            "genuine_acceptance_rate",
            "false_reject_rate",
            "impostor_false_accept_rate",
            "impostor_correct_rejection_rate",
            "overall_top1_accuracy",
            "num_known_queries",
            "num_unknown_queries",
        ]
    )
    return pd.DataFrame(rows)[columns]


def main():
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Evaluate a trained speaker-verification/identification model."
    )
    parser.add_argument(
        "--config", required=True, help="Path to the YAML configuration file."
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="Checkpoint path. Overrides evaluation.checkpoint_path in the config.",
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip speaker verification evaluation (EER / minDCF).",
    )
    parser.add_argument(
        "--skip-identification",
        action="store_true",
        help="Skip speaker identification evaluation (top-k accuracy).",
    )
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as config_file:
        cfg = yaml.safe_load(config_file)

    device = get_device()
    evaluation_cfg = cfg["evaluation"]
    checkpoint_path = args.checkpoint or evaluation_cfg["checkpoint_path"]
    LOGGER.info("Startup | config=%s | device=%s", args.config, device)
    LOGGER.info("Loading checkpoint | %s", checkpoint_path)

    # TensorBoard logging, using the same technique as train.py: a single
    # SummaryWriter, config dumped as run/config text, and metrics written as
    # scalars under an "evaluation/" namespace.
    writer = None
    if evaluation_cfg.get("log", False):
        log_dir = evaluation_cfg.get("log_dir", "./logs/eval")
        writer = SummaryWriter(log_dir=log_dir)
        writer.add_text("run/config", yaml.safe_dump(cfg), 0)
        LOGGER.info("Logging enabled | TensorBoard event directory: %s", log_dir)
    else:
        LOGGER.info(
            "Logging disabled | Set evaluation.log=true to enable TensorBoard events."
        )

    encoder = build_encoder(cfg["model"]).to(device)
    epoch = load_checkpoint(encoder, checkpoint_path, device)
    LOGGER.info("Model ready | checkpoint_epoch=%s", epoch)
    # Used as the TensorBoard step for evaluation scalars; falls back to 0
    # if the checkpoint doesn't record an epoch number.
    step = epoch if isinstance(epoch, int) else 0

    data_cfg = cfg["data"]
    features_cfg = cfg["features"]
    feature_dataset = SpeakerDataset(
        f"{data_cfg['manifest_dir']}/val.csv",
        sample_rate=data_cfg["sample_rate"],
        max_duration=data_cfg["max_duration"],
        n_mels=features_cfg["n_mels"],
        n_fft=features_cfg["n_fft"],
        win_length=features_cfg["win_length"],
        hop_length=features_cfg["hop_length"],
        train_mode=False,
        min_duration=data_cfg["min_duration"],
    )

    # --- Speaker verification: gates "important" functions -----------------
    # NOTE: `dcf_threshold` (not `eer_threshold`) is the operating threshold the
    # assistant should use in production to authorize sensitive actions, since
    # minDCF is computed against the cost weights (dcf_p_target/c_miss/c_fa) that
    # reflect how much worse a false accept is than a false reject for this
    # use case, whereas EER just balances the two equally.
    if not args.skip_verification:
        LOGGER.info(
            "Verification started | verification_trial_list=%s",
            evaluation_cfg["verification_trial_list"],
        )
        sv_results = evaluate_verification(
            encoder,
            feature_dataset,
            evaluation_cfg["verification_trial_list"],
            device,
            evaluation_cfg,
        )
        LOGGER.info(
            "Verification completed | EER=%.4f%% (threshold=%.6f) | "
            "minDCF=%.6f (threshold=%.6f, USE THIS AS THE SECURITY THRESHOLD) | "
            "normalized_minDCF=%.4f",
            sv_results["eer"] * 100,
            sv_results["eer_threshold"],
            sv_results["min_dcf"],
            sv_results["dcf_threshold"],
            sv_results["normalized_min_dcf"],
        )
        if writer is not None:
            writer.add_scalar("evaluation/eer", sv_results["eer"], step)
            writer.add_scalar("evaluation/min_dcf", sv_results["min_dcf"], step)
            writer.add_scalar(
                "evaluation/normalized_min_dcf",
                sv_results["normalized_min_dcf"],
                step,
            )
            writer.flush()
    else:
        LOGGER.info("Verification evaluation skipped (--skip-verification)")

    # --- Speaker identification: powers personalization ---------------------
    # Always open-set: queries are KNOWN (enrolled) or UNKNOWN (not enrolled).
    # The rejection threshold is picked from val_list alone -- it is NEVER
    # derived from identification_test_list (open_set_identification_trials.csv)
    # or from the verification trial list, so the number reported here is a
    # genuine held-out evaluation of the auto-selected threshold.
    if not args.skip_identification:
        required_identification_keys = {
            "enrollment_list",
            "identification_test_list",
            "val_list",
        }
        if not required_identification_keys.issubset(evaluation_cfg):
            LOGGER.warning(
                "Identification lists missing from the 'evaluation' section; skipping "
                "identification evaluation. Add 'evaluation.enrollment_list', "
                "'evaluation.val_list', and 'evaluation.identification_test_list' to "
                "enable it."
            )
        else:
            centroids = build_speaker_centroids(
                encoder, feature_dataset, evaluation_cfg["enrollment_list"], device
            )
            top_k = tuple(evaluation_cfg.get("top_k", [1, 5]))
            max_k = max(top_k)

            # The minDCF-optimal ("recommended") threshold and, if enabled, the
            # sweep grid are BOTH derived only from val_list -- never from
            # identification_test_list. A manual evaluation.threshold override
            # (if set) short-circuits all of this into a single-row table.
            manual_override = evaluation_cfg.get("threshold")
            sweep_cfg = evaluation_cfg.get("threshold_sweep") or {}
            if manual_override is not None:
                LOGGER.info(
                    "Using evaluation.threshold override for open-set identification "
                    "(sweep disabled): %.6f",
                    manual_override,
                )
                auto_threshold = None
                thresholds = [float(manual_override)]
            else:
                val_labels, val_scores = score_val_trials(
                    encoder,
                    feature_dataset,
                    evaluation_cfg["val_list"],
                    centroids,
                    device,
                )
                auto_threshold = select_mindcf_threshold(
                    val_labels, val_scores, evaluation_cfg
                )
                if sweep_cfg.get("enabled", False):
                    thresholds = build_threshold_grid(
                        val_scores, sweep_cfg, auto_threshold
                    )
                    LOGGER.info(
                        "Threshold sweep enabled | %d threshold(s) to evaluate: %s",
                        len(thresholds),
                        thresholds,
                    )
                else:
                    thresholds = [auto_threshold]

            LOGGER.info(
                "Identification started | enrollment_list=%s | "
                "identification_test_list=%s | mode=open-set | thresholds=%d",
                evaluation_cfg["enrollment_list"],
                evaluation_cfg["identification_test_list"],
                len(thresholds),
            )
            records = score_identification_queries(
                encoder,
                feature_dataset,
                centroids,
                evaluation_cfg["identification_test_list"],
                device,
                max_k,
            )
            table = evaluate_identification_sweep(
                records, thresholds, top_k, auto_threshold=auto_threshold
            )

            LOGGER.info(
                "Identification completed | threshold table (%d row(s)):\n%s",
                len(table),
                table.to_string(index=False),
            )

            results_csv = evaluation_cfg.get("results_csv")
            if results_csv:
                out_dir = os.path.dirname(results_csv)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                table.to_csv(results_csv, index=False)
                LOGGER.info("Threshold table saved to %s", results_csv)

            if writer is not None:
                writer.add_text(
                    "evaluation/threshold_table", table.to_string(index=False), step
                )
                # Headline scalars (for cross-epoch TensorBoard tracking) come
                # from the recommended row: the auto/minDCF threshold if one
                # was computed, otherwise the single manual-override row.
                recommended_rows = (
                    table[table["recommended_auto_threshold"]]
                    if auto_threshold is not None
                    else table.iloc[0:0]
                )
                if not recommended_rows.empty:
                    recommended = recommended_rows.iloc[0]
                elif auto_threshold is not None:
                    # Safety net: e.g. threshold_sweep.values was set explicitly
                    # and happens not to contain the auto threshold. Fall back
                    # to whichever grid row is numerically closest to it.
                    closest_idx = (table["threshold"] - auto_threshold).abs().idxmin()
                    recommended = table.loc[closest_idx]
                else:
                    recommended = table.iloc[0]
                scalar_names = [f"top{k}_accuracy_given_accept" for k in top_k] + [
                    "genuine_acceptance_rate",
                    "false_reject_rate",
                    "impostor_false_accept_rate",
                    "impostor_correct_rejection_rate",
                    "overall_top1_accuracy",
                ]
                for name in scalar_names:
                    writer.add_scalar(f"evaluation/{name}", recommended[name], step)
                writer.flush()
    else:
        LOGGER.info("Identification evaluation skipped (--skip-identification)")

    if writer is not None:
        writer.close()
        LOGGER.info(
            "TensorBoard logging completed | %s",
            evaluation_cfg.get("log_dir", "./logs/eval"),
        )


if __name__ == "__main__":
    main()
