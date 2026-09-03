"""
Prepare Data for Vietnam-Celeb Dataset
=======================================
Run this after manually DOWNLOADING the four zip parts from Google Drive
and extracting them with:

    zip -F vietnam-celeb-part.zip --out full-dataset.zip
    unzip full-dataset.zip

After extraction, you will have the following components (placed at the same
level or specified through command-line arguments):

    data/                       <- one directory per speaker, directory name =
                                   speaker_id
        id00001/
            00000.wav
            00001.wav
            ...
        id00002/
            ...
    vietnam-celeb-t.txt        <- utterance list used for TRAINING
                                   (each line: "idXXXXX/YYYYY.wav")
    vietnam-celeb-e.txt        <- EASY test trials
                                   (each line: "label,path1,path2" or
                                   "label path1 path2", label: 1=same
                                   speaker (target), 0=different speaker)
    vietnam-celeb-h.txt        <- HARD test trials, same format
    speaker-metadata.csv       <- (optional) speaker_id, gender, dialect, source

This script produces exactly four manifest files:

    manifests/
    ├── train.csv                               <- training utterances; ALSO used
    │                                              directly as the SID enrollment/
    │                                              reference set (build centroids
    │                                              from it at evaluation time).
    ├── val.csv                                 <- held-out utterances from the
    │                                              SAME speakers as train.csv.
    │                                              Used to monitor loss/accuracy
    │                                              AND to auto-derive the open-set
    │                                              identification threshold.
    ├── verification_trials.csv                 <- closed-set speaker-verification
    │                                              (SV) trial pairs, for EER/minDCF.
    └── open_set_identification_trials.csv      <- open-set speaker-identification
                                                   (SID) queries, each labeled
                                                   KNOWN (speaker is in train.csv /
                                                   the enrollment set) or UNKNOWN
                                                   (speaker is not enrolled).

This script:
  1. Reads vietnam-celeb-t.txt -> training utterance list.
  2. Splits a small portion of the training utterances from each SPEAKER into
     VALIDATION (the original dataset only provides train/test splits
     and no separate validation set). By default, the split is performed by
     utterance ratio within each speaker, not by speaker, to preserve the
     number of classes during training. This is used to monitor loss/accuracy,
     and val.csv doubles as the data used to automatically pick the open-set
     identification rejection threshold (see evaluate.py). It is NEVER used to
     determine that threshold from open_set_identification_trials.csv itself.
  3. Reads vietnam-celeb-e.txt and vietnam-celeb-h.txt -> combines them into
     verification_trials.csv for speaker-verification (SV) EER/minDCF
     evaluation (closed-set: label 1 = same speaker, 0 = different speaker).
  4. Builds open_set_identification_trials.csv:
       - KNOWN queries   = the validation utterances (val.csv), whose speakers
                            are, by construction, also in train.csv/enrollment.
       - UNKNOWN queries = the unique utterances referenced by the Easy/Hard
                            trial files, MINUS any utterance whose speaker is
                            also present in train.csv/enrollment. The dataset
                            itself does NOT guarantee that Easy/Hard trial
                            speakers are disjoint from train speakers, so this
                            filtering is done explicitly in
                            collect_unknown_queries() (and the number of
                            excluded speakers/utterances is printed in the
                            summary) to keep the open-set protocol valid.
  5. Prints complete statistics for direct inclusion in the report
     (Dataset & Splits section).

Usage (place this script alongside the data/ directory and .txt files, or
specify absolute paths):

    python prepare_data.py \
        --data-root ./data \
        --train-list ./vietnam-celeb-t.txt \
        --test-easy ./vietnam-celeb-e.txt \
        --test-hard ./vietnam-celeb-h.txt \
        --speaker-meta ./speaker-metadata.csv \
        --out-dir ./manifests \
        --config ../configs/ecapa_config.yaml \
        --val-ratio 0.1 \
        --seed 1234

The minimum utterance duration is always read from data.min_duration in the
YAML configuration. This keeps generated manifests consistent with train.py.
"""

import argparse
import csv
import os
import random
from collections import defaultdict
from pathlib import Path

import soundfile as sf
import yaml


def get_duration(path: str) -> float:
    try:
        info = sf.info(path)
        return info.frames / info.samplerate
    except Exception:
        return -1.0


def parse_train_list(train_list_path, data_root):
    """Read vietnam-celeb-t.txt -> list of (speaker_id, rel_path, abs_path)."""
    entries = []
    missing = 0
    with open(train_list_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Support both "speaker/file.wav" and "speaker file.wav" formats.
            parts = line.replace(",", " ").split()
            if len(parts) >= 2 and "/" not in parts[-1] and "\\" not in parts[-1]:
                rel_path = os.path.join(parts[-2], parts[-1])
            else:
                rel_path = parts[-1]
            rel_path = rel_path.strip()
            rel_path = rel_path.replace("\\", "/")
            spk = rel_path.split("/")[0]
            abs_path = os.path.join(data_root, rel_path)
            if not os.path.isfile(abs_path):
                missing += 1
                continue
            entries.append((spk, rel_path, abs_path))
    if missing:
        print(
            f"[WARNING] {missing} training utterances could not be found "
            f"(check whether --data-root points to the correct extracted "
            f"'data' directory)."
        )
    return entries


def parse_trial_file(trial_path, data_root):
    """Read trial-pair files (vietnam-celeb-e.txt / -h.txt).

    Accepts both comma-separated and whitespace-separated formats:
        1,id00896/00002.wav,id00896/00001.wav
        1 id00896/00002.wav id00896/00001.wav
    """
    trials = []
    missing = 0
    with open(trial_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
            else:
                parts = line.split()
            if len(parts) != 3:
                continue
            label, p1, p2 = parts
            abs1 = os.path.join(data_root, p1)
            abs2 = os.path.join(data_root, p2)
            if not (os.path.isfile(abs1) and os.path.isfile(abs2)):
                missing += 1
                continue
            trials.append((abs1, abs2, int(label)))
    if missing:
        print(
            f"[WARNING] {missing} trial pairs in {os.path.basename(trial_path)} "
            f"were skipped because audio files were missing."
        )
    return trials


def split_train_val(entries, val_ratio, min_duration, seed):
    """Keep ALL speakers in both train and validation sets (speaker-closed).

    Split by utterance ratio per speaker for monitoring loss/accuracy during
    training. Do NOT use this split to calculate EER. EER is calculated on
    verification_trials.csv, where speakers are completely separated
    according to the original dataset design.
    """
    rng = random.Random(seed)
    by_spk = defaultdict(list)
    for spk, rel_path, abs_path in entries:
        by_spk[spk].append((rel_path, abs_path))

    rows_train, rows_val = [], []
    for spk, files in by_spk.items():
        files = files[:]
        rng.shuffle(files)
        kept = []
        for rel_path, abs_path in files:
            dur = get_duration(abs_path)
            if dur >= min_duration:
                kept.append((rel_path, abs_path, dur))
        if len(kept) < 2:
            # Not enough files to create a validation split;
            # put all files into training.
            for i, (rel_path, abs_path, dur) in enumerate(kept):
                rows_train.append(
                    [f"{spk}_{i:04d}", spk, abs_path, f"{dur:.2f}", "train"]
                )
            continue
        n_val = max(1, int(len(kept) * val_ratio))
        val_files = kept[:n_val]
        train_files = kept[n_val:]
        for i, (rel_path, abs_path, dur) in enumerate(train_files):
            rows_train.append([f"{spk}_{i:04d}", spk, abs_path, f"{dur:.2f}", "train"])
        for i, (rel_path, abs_path, dur) in enumerate(val_files):
            rows_val.append([f"{spk}_{i:04d}", spk, abs_path, f"{dur:.2f}", "val"])
    return rows_train, rows_val


def write_manifest(rows, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["utt_id", "speaker_id", "file_path", "duration", "split"])
        for r in rows:
            writer.writerow(r)
    print(f"[OK] Wrote {len(rows)} rows -> {out_path}")


def write_trials(trials, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["enrollment_path", "test_path", "label"])
        for a, b, label in trials:
            writer.writerow([a, b, label])
    print(f"[OK] Wrote {len(trials)} trial pairs -> {out_path}")


def collect_unknown_queries(trials, train_speakers):
    """Extract unique (speaker_id, file_path) pairs from SV trial pairs to
    use as UNKNOWN queries for open-set identification.

    IMPORTANT: the Easy/Hard trial files are plain speaker-verification
    trial pairs. The dataset does NOT guarantee that their speakers are
    disjoint from the training list -- some speakers can legitimately show
    up in both vietnam-celeb-t.txt and vietnam-celeb-e.txt/-h.txt. Since an
    UNKNOWN query must never belong to an already-enrolled/train speaker
    (otherwise the open-set identification protocol is invalid), any
    utterance whose speaker is present in train_speakers is explicitly
    excluded here. The excluded speakers/utterances are returned so the
    caller can report them in the summary instead of silently dropping them.
    """
    seen = set()
    rows = []
    excluded_speakers = set()
    excluded_utts = 0
    for path_a, path_b, _ in trials:
        for path in (path_a, path_b):
            if path in seen:
                continue
            seen.add(path)
            spk = os.path.basename(os.path.dirname(path))
            if spk in train_speakers:
                excluded_speakers.add(spk)
                excluded_utts += 1
                continue
            rows.append([spk, path, "UNKNOWN"])
    return rows, excluded_speakers, excluded_utts


def write_open_set_identification(rows_val, unknown_rows, out_path):
    """Write open_set_identification_trials.csv.

    KNOWN queries come from rows_val (validation utterances of enrolled/train
    speakers); UNKNOWN queries come from unknown_rows (test-set utterances
    whose speakers are absent from the enrollment set). This file is used
    ONLY for the final open-set evaluation -- never for picking the
    rejection threshold, which is derived from val.csv instead.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["speaker_id", "file_path", "query_type"])
        for row in rows_val:
            # rows_val entries: [utt_id, speaker_id, file_path, duration, split]
            writer.writerow([row[1], row[2], "KNOWN"])
        for row in unknown_rows:
            writer.writerow(row)
    n_known = len(rows_val)
    n_unknown = len(unknown_rows)
    print(
        f"[OK] Wrote {n_known + n_unknown} identification queries "
        f"({n_known} KNOWN, {n_unknown} UNKNOWN) -> {out_path}"
    )


def load_speaker_metadata(path):
    if not path or not os.path.isfile(path):
        return None
    import pandas as pd

    sep = "\t" if path.endswith(".tsv") else ","
    return pd.read_csv(path, sep=sep)


def main():
    ap = argparse.ArgumentParser()
    default_config = (
        Path(__file__).resolve().parents[1] / "configs" / "ecapa_config.yaml"
    )
    ap.add_argument(
        "--config",
        default=str(default_config),
        help="Training YAML configuration (default: project's ecapa_config.yaml)",
    )
    ap.add_argument(
        "--data-root",
        required=True,
        help="The 'data' directory containing subdirectories id00001, "
        "id00002, ... (created after extracting full-dataset.zip)",
    )
    ap.add_argument(
        "--train-list",
        required=True,
        help="Path to vietnam-celeb-t.txt",
    )
    ap.add_argument(
        "--test-easy",
        required=True,
        help="Path to vietnam-celeb-e.txt",
    )
    ap.add_argument(
        "--test-hard",
        required=True,
        help="Path to vietnam-celeb-h.txt",
    )
    ap.add_argument(
        "--speaker-meta",
        default=None,
        help="(Optional) Path to speaker-metadata.csv/tsv",
    )
    ap.add_argument(
        "--out-dir",
        default=None,
        help="Manifest output directory (default: data.manifest_dir from --config)",
    )
    ap.add_argument(
        "--val-ratio",
        type=float,
        default=0.1,
        help="Utterance/speaker ratio split into validation from the original "
        "training set",
    )
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    with open(config_path, encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    try:
        min_duration = float(config["data"]["min_duration"])
        configured_manifest_dir = Path(config["data"]["manifest_dir"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "The configuration must define data.min_duration and data.manifest_dir."
        ) from exc
    if not configured_manifest_dir.is_absolute():
        # The config is stored in models/configs, while manifest_dir is relative
        # to the models directory where train.py is run.
        configured_manifest_dir = config_path.parent.parent / configured_manifest_dir
    out_dir = args.out_dir or str(configured_manifest_dir)
    print(f"[INFO] Using data.min_duration={min_duration:.2f}s " f"from {config_path}")
    print(f"[INFO] Writing manifests to {out_dir}")

    print(f"[INFO] Reading training list from {args.train_list} ...")
    train_entries = parse_train_list(args.train_list, args.data_root)
    n_spk_train = len(set(e[0] for e in train_entries))
    print(
        f"[INFO] Original training set: {len(train_entries)} utterances, "
        f"{n_spk_train} speakers."
    )

    print(f"[INFO] Splitting training/validation " f"(val_ratio={args.val_ratio}) ...")
    rows_train, rows_val = split_train_val(
        train_entries, args.val_ratio, min_duration, args.seed
    )
    write_manifest(rows_train, os.path.join(out_dir, "train.csv"))
    write_manifest(rows_val, os.path.join(out_dir, "val.csv"))

    # train.csv doubles as the SID enrollment/reference set (speakers are
    # registered by averaging their training-utterance embeddings into
    # centroids at evaluation time) -- no separate enrollment.csv is written.

    print(f"[INFO] Reading Easy test trials from {args.test_easy} ...")
    trials_easy = parse_trial_file(args.test_easy, args.data_root)
    print(f"[INFO] Reading Hard test trials from {args.test_hard} ...")
    trials_hard = parse_trial_file(args.test_hard, args.data_root)
    trials_all = trials_easy + trials_hard

    # Closed-set SV trials (replaces the old test_trials.csv).
    write_trials(trials_all, os.path.join(out_dir, "verification_trials.csv"))

    # train_speakers must be known BEFORE building UNKNOWN queries, since any
    # Easy/Hard-trial speaker that also appears in train has to be excluded
    # (see collect_unknown_queries) to keep the open-set design valid.
    train_speakers = set(e[0] for e in train_entries)

    # Open-set SID trials: KNOWN queries are the validation utterances
    # (same speakers as train.csv/enrollment); UNKNOWN queries are the
    # test-set utterances referenced by the Easy/Hard trial files, with any
    # speaker that overlaps train explicitly filtered out.
    unknown_rows, excluded_speakers, excluded_utts = collect_unknown_queries(
        trials_all, train_speakers
    )
    write_open_set_identification(
        rows_val,
        unknown_rows,
        os.path.join(out_dir, "open_set_identification_trials.csv"),
    )

    # Verify the open-set split is now strictly speaker-disjoint.
    test_speakers = set(row[0] for row in unknown_rows)
    overlap = train_speakers & test_speakers
    assert not overlap, (
        f"Open-set design still violated: {len(overlap)} speakers overlap "
        f"between train and test after filtering -- this should not happen."
    )

    meta = load_speaker_metadata(args.speaker_meta)

    print("\n===== SUMMARY (for the Dataset & Splits section) =====")
    print(f"Train  : {len(rows_train):6d} utterances | {n_spk_train:4d} speakers")
    print(
        f"Val    : {len(rows_val):6d} utterances | "
        f"(same {n_spk_train} speakers as train)"
    )
    print(f"Test   : {len(test_speakers):4d} speakers " f"(NO overlap with train)")
    print(f"  - Easy trials : {len(trials_easy)}")
    print(f"  - Hard trials : {len(trials_hard)}")
    print(f"  - Total trials: {len(trials_all)}")
    print(
        f"Speakers overlapping between train and test: {len(overlap)} "
        f"(must be = 0 for the correct open-set design)"
    )
    if excluded_speakers:
        print(
            f"  [NOTE] {len(excluded_speakers)} speakers "
            f"({excluded_utts} utterances) referenced in the Easy/Hard "
            f"trial files also appear in train.csv and were EXCLUDED from "
            f"UNKNOWN queries to keep the open-set design valid."
        )
    print(
        f"SID enrollment (train.csv)      : {len(rows_train):6d} utterances | "
        f"{n_spk_train:4d} registered speakers"
    )
    print(
        f"Open-set SID queries            : {len(rows_val) + len(unknown_rows):6d} total | "
        f"{len(rows_val):6d} KNOWN (val.csv) | {len(unknown_rows):6d} UNKNOWN (test speakers)"
    )
    if meta is not None:
        print("\n--- Speaker metadata statistics (if available) ---")
        if "gender" in meta.columns:
            print("By gender:\n", meta["gender"].value_counts().to_string())
        if "dialect" in meta.columns:
            print(
                "By region/dialect:\n",
                meta["dialect"].value_counts().to_string(),
            )


if __name__ == "__main__":
    main()