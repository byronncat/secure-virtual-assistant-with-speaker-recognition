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

import pandas as pd
import torch
import torch.nn.functional as F
import yaml
from torch.utils.tensorboard import SummaryWriter

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
        for index, path in enumerate(paths, start=1):
            embeddings[path] = embed_path(encoder, feature_dataset, path, device)
            if index % 100 == 0 or index == len(paths):
                LOGGER.info("Embedding progress | %d/%d files", index, len(paths))

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
        for speaker_id, group in enrollment.groupby("speaker_id"):
            embeds = [
                embed_path(encoder, feature_dataset, path, device)
                for path in group["file_path"]
            ]
            centroid = torch.mean(torch.cat(embeds, dim=0), dim=0, keepdim=True)
            centroids[speaker_id] = F.normalize(centroid, dim=-1)
    return centroids


def determine_open_set_threshold(
    encoder, feature_dataset, val_list, centroids, device, dcf_cfg
):
    """Automatically determine the open-set identification rejection
    threshold from val.csv ONLY -- never from open_set_identification_trials.csv.

    val.csv utterances belong to the same speakers as the enrollment set
    (train.csv, speaker-closed split). For every val.csv utterance we score
    it against every enrolled speaker's centroid: the score against its own
    true speaker forms a genuine trial, and the scores against every other
    enrolled speaker form impostor trials. The minDCF-optimal threshold over
    these genuine/impostor scores (using the same dcf_p_target/c_miss/c_fa
    cost weights as verification) is fixed and returned; the caller reuses
    it unchanged on open_set_identification_trials.csv.
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
        "Determining open-set threshold from val_list | val_utterances=%d | "
        "enrolled_speakers=%d",
        len(val_queries),
        len(speaker_ids),
    )

    labels, scores = [], []
    encoder.eval()
    with torch.no_grad():
        for index, row in enumerate(val_queries.itertuples(index=False), start=1):
            if row.speaker_id not in centroids:
                # Should not happen given the speaker-closed train/val split.
                continue
            embedding = embed_path(encoder, feature_dataset, row.file_path, device)
            sims = (embedding @ centroid_matrix.T).squeeze(0).tolist()
            for sid, sim in zip(speaker_ids, sims):
                labels.append(1 if sid == row.speaker_id else 0)
                scores.append(sim)
            if index % 100 == 0 or index == len(val_queries):
                LOGGER.info(
                    "Threshold-search progress | %d/%d val utterances",
                    index,
                    len(val_queries),
                )

    _, _, dcf_threshold = compute_min_dcf(
        labels,
        scores,
        p_target=dcf_cfg["dcf_p_target"],
        c_miss=dcf_cfg["dcf_c_miss"],
        c_fa=dcf_cfg["dcf_c_fa"],
    )
    LOGGER.info(
        "Open-set identification threshold fixed from val_list: %.6f", dcf_threshold
    )
    return dcf_threshold


def evaluate_identification(
    encoder,
    feature_dataset,
    centroids,
    identification_test_list,
    device,
    top_k=(1, 5),
    reject_threshold=None,
):
    """Open-set speaker identification evaluation.

    Every query in `identification_test_list` is compared against all
    enrolled speaker centroids (from `centroids`, built from train.csv). If
    the best similarity score clears `reject_threshold`, the query is
    accepted and assigned to its best-matching enrolled speaker (top-k
    accuracy is then computed among accepted, genuinely-enrolled queries);
    otherwise it is rejected, i.e. predicted UNKNOWN. The trial list mixes:
      * KNOWN queries   -> speaker_id IS in the enrollment set (genuine)
      * UNKNOWN queries -> speaker_id is NOT in the enrollment set (impostor)
    This mirrors how the assistant should behave at runtime: identify for
    personalization, but fall back to a generic/guest profile when the match
    isn't confident enough, and never rely on this weaker threshold to
    authorize sensitive actions (that's what verification's minDCF
    threshold is for).
    """
    if reject_threshold is None:
        raise ValueError(
            "evaluate_identification requires a reject_threshold for open-set "
            "evaluation (set evaluation.threshold in the config, or let it be "
            "auto-derived from val_list)."
        )

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

    max_k = max(top_k)
    LOGGER.info(
        "Running open-set identification | test_utterances=%d | "
        "enrolled_speakers=%d | reject_threshold=%.6f",
        len(identification_queries),
        len(speaker_ids),
        reject_threshold,
    )

    correct_at_k = {k: 0 for k in top_k}
    genuine_total = 0
    genuine_accepted = 0
    impostor_total = 0
    impostor_accepted = (
        0  # false accepts: UNKNOWN voice wrongly matched to an enrolled speaker
    )

    encoder.eval()
    with torch.no_grad():
        for index, row in enumerate(
            identification_queries.itertuples(index=False), start=1
        ):
            is_genuine = row.speaker_id in enrolled_set  # KNOWN vs UNKNOWN
            embedding = embed_path(encoder, feature_dataset, row.file_path, device)
            scores = (embedding @ centroid_matrix.T).squeeze(0)
            top_indices = torch.topk(
                scores, k=min(max_k, len(speaker_ids))
            ).indices.tolist()
            ranked = [speaker_ids[i] for i in top_indices]
            best_score = scores[top_indices[0]].item()
            accepted = best_score >= reject_threshold

            if is_genuine:
                genuine_total += 1
                if accepted:
                    genuine_accepted += 1
                    for k in top_k:
                        if row.speaker_id in ranked[:k]:
                            correct_at_k[k] += 1
                # rejected genuine (KNOWN) trials count as false rejects below.
            else:
                impostor_total += 1
                if accepted:
                    impostor_accepted += 1

            if index % 100 == 0 or index == len(identification_queries):
                LOGGER.info(
                    "Identification progress | %d/%d files",
                    index,
                    len(identification_queries),
                )

    results = {
        f"top{k}_accuracy_given_accept": (
            correct_at_k[k] / genuine_accepted if genuine_accepted else 0.0
        )
        for k in top_k
    }
    results["genuine_acceptance_rate"] = (
        genuine_accepted / genuine_total if genuine_total else 0.0
    )
    results["false_reject_rate"] = 1.0 - results["genuine_acceptance_rate"]
    if impostor_total:
        results["impostor_false_accept_rate"] = impostor_accepted / impostor_total
        results["impostor_correct_rejection_rate"] = (
            1.0 - results["impostor_false_accept_rate"]
        )
    # Overall open-set accuracy: genuine (KNOWN) correctly accepted AND top-1 correct.
    results["overall_top1_accuracy"] = (
        correct_at_k[top_k[0]] / genuine_total if genuine_total else 0.0
    )
    return results


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

            reject_threshold = evaluation_cfg.get("threshold")
            if reject_threshold is None:
                reject_threshold = determine_open_set_threshold(
                    encoder,
                    feature_dataset,
                    evaluation_cfg["val_list"],
                    centroids,
                    device,
                    evaluation_cfg,
                )
            else:
                LOGGER.info(
                    "Using evaluation.threshold override for open-set identification: "
                    "%.6f",
                    reject_threshold,
                )

            LOGGER.info(
                "Identification started | enrollment_list=%s | "
                "identification_test_list=%s | mode=open-set",
                evaluation_cfg["enrollment_list"],
                evaluation_cfg["identification_test_list"],
            )
            top_k = tuple(evaluation_cfg.get("top_k", [1, 5]))
            sid_results = evaluate_identification(
                encoder,
                feature_dataset,
                centroids,
                evaluation_cfg["identification_test_list"],
                device,
                top_k=top_k,
                reject_threshold=reject_threshold,
            )
            LOGGER.info(
                "Identification completed | %s",
                " | ".join(
                    f"{name}={value * 100:.2f}%" for name, value in sid_results.items()
                ),
            )
            if writer is not None:
                for name, value in sid_results.items():
                    writer.add_scalar(f"evaluation/{name}", value, step)
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
