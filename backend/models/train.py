"""
train.py
========
ECAPA-TDNN training loop for speaker verification/identification.

Usage:
    python train.py --config configs/ecapa_config.yaml
"""

import argparse
import logging
import os
import shutil
import time

# --- Avoid CPU oversubscription with multiple DataLoader workers ----------
# Each DataLoader worker is a separate process. Libraries used inside
# dataset.py (torchaudio's resampling/MelSpectrogram, which lean on
# OpenMP/MKL for their FFTs) default to spawning one thread PER AVAILABLE
# CORE, per process. With num_workers>1 that means N worker processes each
# trying to use every core simultaneously, which causes heavy context-
# switching/cache thrashing and can make training much SLOWER than with
# fewer workers. Pinning each process's internal thread pool to 1 lets
# parallelism come from the workers themselves instead. This must run
# before torch/torchaudio are imported (including transitively, via the
# `from dataset import ...` below) to reliably take effect.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import pandas as pd
import torch
import torch.nn.functional as F
import yaml
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm.auto import tqdm

from dataset import SpeakerDataset, collate_fn
from metrics import compute_eer, compute_min_dcf, top_k_accuracy
from model import build_model_and_loss

# Also cap the main process's own thread pool for the same reason -- it
# does the val_set verification embedding (single-process) and otherwise
# would compete with the worker processes for cores too.
torch.set_num_threads(1)

LOGGER = logging.getLogger("speaker_training")


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


def run_epoch(
    encoder,
    classifier,
    criterion,
    loader,
    optimizer,
    device,
    grad_clip,
    log,
    epoch,
    writer=None,
    global_step=0,
    train=True,
):
    encoder.train(train)
    classifier.train(train)
    total_loss, total_acc, n_batches = 0.0, 0.0, 0

    phase = "Train" if train else "Validation"
    progress = tqdm(
        loader,
        desc=f"Epoch {epoch:03d} {phase}",
        leave=False,
        disable=not log,
    )
    for feats, labels in progress:
        feats, labels = feats.to(device), labels.to(device)

        with torch.set_grad_enabled(train):
            emb = encoder(feats)
            logits_cosine = classifier(emb)
            # SpeechBrain's LogSoftmaxWrapper expects (B, 1, C) and labels (B, 1).
            loss = criterion(logits_cosine.unsqueeze(1), labels.unsqueeze(1))

            if train:
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    list(encoder.parameters()) + list(classifier.parameters()),
                    grad_clip,
                )
                optimizer.step()

        acc = top_k_accuracy(logits_cosine.detach(), labels, k=1)
        total_loss += loss.item()
        total_acc += acc
        n_batches += 1

        progress.set_postfix(loss=f"{loss.item():.4f}", acc=f"{acc:.4f}")
        if train and writer is not None:
            writer.add_scalar("batch/train_loss", loss.item(), global_step)
            writer.add_scalar("batch/train_accuracy", acc, global_step)
            writer.add_scalar(
                "batch/learning_rate", optimizer.param_groups[0]["lr"], global_step
            )
            global_step += 1

    return total_loss / max(n_batches, 1), total_acc / max(n_batches, 1), global_step


def evaluate_verification(encoder, dataset, trial_list, device, evaluation_cfg):
    """Calculate verification metrics from enrollment/test trial pairs."""
    trials = pd.read_csv(trial_list)
    required = {"enrollment_path", "test_path", "label"}
    if not required.issubset(trials.columns):
        raise ValueError(f"Trial list must contain columns: {sorted(required)}")

    embeddings = {}
    encoder.eval()
    with torch.no_grad():
        for path in pd.concat(
            [trials["enrollment_path"], trials["test_path"]]
        ).unique():
            feats = dataset.extract_features_full(path).unsqueeze(0).to(device)
            embeddings[path] = F.normalize(encoder(feats), dim=-1).cpu()

    scores = [
        float((embeddings[row.enrollment_path] * embeddings[row.test_path]).sum())
        for row in trials.itertuples(index=False)
    ]
    labels = trials["label"].to_numpy()
    eer, _ = compute_eer(labels, scores)
    min_dcf, min_dcf_norm, _ = compute_min_dcf(
        labels,
        scores,
        p_target=evaluation_cfg["dcf_p_target"],
        c_miss=evaluation_cfg["dcf_c_miss"],
        c_fa=evaluation_cfg["dcf_c_fa"],
    )
    return {
        "eer": eer,
        "min_dcf": min_dcf,
        "normalized_min_dcf": min_dcf_norm,
    }


def main():
    configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    torch.manual_seed(cfg["seed"])
    device = get_device()
    LOGGER.info(
        "Startup | config=%s | seed=%s | device=%s", args.config, cfg["seed"], device
    )

    writer = None
    if cfg["training"]["log"]:
        writer = SummaryWriter(log_dir=cfg["training"]["log_dir"])
        writer.add_text("run/config", yaml.safe_dump(cfg), 0)
        LOGGER.info(
            "Logging enabled | TensorBoard event directory: %s",
            cfg["training"]["log_dir"],
        )
    else:
        LOGGER.info(
            "Logging disabled | Set training.log=true to enable progress and TensorBoard events."
        )

    manifest_dir = cfg["data"]["manifest_dir"]
    aug_cfg = cfg.get("augmentation", {})
    LOGGER.info(
        "Dataset initialization | manifest_dir=%s | augmentation_enabled=%s",
        manifest_dir,
        aug_cfg.get("enabled", False),
    )
    train_set = SpeakerDataset(
        os.path.join(manifest_dir, "train.csv"),
        sample_rate=cfg["data"]["sample_rate"],
        max_duration=cfg["data"]["max_duration"],
        n_mels=cfg["features"]["n_mels"],
        n_fft=cfg["features"]["n_fft"],
        win_length=cfg["features"]["win_length"],
        hop_length=cfg["features"]["hop_length"],
        train_mode=True,
        min_duration=cfg["data"]["min_duration"],
        augment=aug_cfg.get("enabled", False),
        freq_mask_param=aug_cfg.get("freq_mask_param", 0),
        time_mask_param=aug_cfg.get("time_mask_param", 0),
        num_freq_masks=aug_cfg.get("num_freq_masks", 0),
        num_time_masks=aug_cfg.get("num_time_masks", 0),
        gain_db_range=tuple(aug_cfg.get("gain_db_range", [0.0, 0.0])),
        gain_prob=aug_cfg.get("gain_prob", 0.0),
    )
    val_set = SpeakerDataset(
        os.path.join(manifest_dir, "val.csv"),
        sample_rate=cfg["data"]["sample_rate"],
        max_duration=cfg["data"]["max_duration"],
        n_mels=cfg["features"]["n_mels"],
        n_fft=cfg["features"]["n_fft"],
        win_length=cfg["features"]["win_length"],
        hop_length=cfg["features"]["hop_length"],
        train_mode=True,  # Keep fixed-length crops for batch loss/accuracy calculation.
        speaker2idx=train_set.speaker2idx,
        min_duration=cfg["data"]["min_duration"],
        augment=False,  # Never augment validation data.
    )
    LOGGER.info(
        "Datasets ready | train_samples=%d | val_samples=%d | speakers=%d | min_duration=%.2fs",
        len(train_set),
        len(val_set),
        len(train_set.speaker2idx),
        cfg["data"]["min_duration"],
    )

    num_workers = cfg["training"]["num_workers"]
    # persistent_workers keeps worker processes alive between epochs instead
    # of tearing them down and re-spawning (which re-imports torchaudio, etc.
    # in each one) every single epoch -- only valid when num_workers > 0.
    # pin_memory speeds up the host->GPU copy, so it's only useful on CUDA.
    persistent_workers = num_workers > 0
    pin_memory = device.type == "cuda"
    train_loader = DataLoader(
        train_set,
        batch_size=cfg["training"]["batch_size"],
        shuffle=True,
        num_workers=num_workers,
        collate_fn=collate_fn,
        drop_last=True,
        persistent_workers=persistent_workers,
        pin_memory=pin_memory,
    )
    val_loader = DataLoader(
        val_set,
        batch_size=cfg["training"]["batch_size"],
        shuffle=False,
        num_workers=num_workers,
        collate_fn=collate_fn,
        persistent_workers=persistent_workers,
        pin_memory=pin_memory,
    )
    LOGGER.info(
        "Data loaders ready | batch_size=%d | workers=%d | persistent_workers=%s | "
        "pin_memory=%s | train_batches=%d | val_batches=%d",
        cfg["training"]["batch_size"],
        num_workers,
        persistent_workers,
        pin_memory,
        len(train_loader),
        len(val_loader),
    )

    num_speakers = len(train_set.speaker2idx)

    encoder, classifier, criterion = build_model_and_loss(cfg, num_speakers)
    encoder.to(device)
    classifier.to(device)

    params = list(encoder.parameters()) + list(classifier.parameters())
    parameter_count = sum(param.numel() for param in params)
    LOGGER.info(
        "Model initialized | encoder=%s | classifier=%s | parameters=%d",
        encoder.__class__.__name__,
        classifier.__class__.__name__,
        parameter_count,
    )
    if cfg["training"]["optimizer"].lower() != "adam":
        raise ValueError(
            "Unsupported training.optimizer. This project supports 'adam'."
        )
    optimizer = torch.optim.Adam(
        params, lr=cfg["training"]["lr"], weight_decay=cfg["training"]["weight_decay"]
    )
    if cfg["training"]["scheduler"].lower() != "exponential":
        raise ValueError(
            "Unsupported training.scheduler. This project supports 'exponential'."
        )
    scheduler = torch.optim.lr_scheduler.ExponentialLR(
        optimizer,
        gamma=(cfg["training"]["lr_final"] / cfg["training"]["lr"])
        ** (1.0 / max(cfg["training"]["num_epochs"], 1)),
    )

    ckpt_dir = cfg["training"]["checkpoint_dir"]
    os.makedirs(ckpt_dir, exist_ok=True)
    LOGGER.info(
        "Training lifecycle started | epochs=%d | optimizer=%s | scheduler=%s | checkpoint_dir=%s",
        cfg["training"]["num_epochs"],
        cfg["training"]["optimizer"],
        cfg["training"]["scheduler"],
        ckpt_dir,
    )

    best_val_loss = float("inf")
    patience = cfg["training"]["early_stopping_patience"]
    bad_epochs = 0
    history = []
    global_step = 0

    eval_every_n_epochs = cfg["training"].get("eval_every_n_epochs", 0)
    save_top_k = cfg["training"].get("save_top_k", 1)
    top_checkpoints = []  # list of (val_loss, path), kept sorted ascending

    for epoch in range(1, cfg["training"]["num_epochs"] + 1):
        t0 = time.time()
        train_loss, train_acc, global_step = run_epoch(
            encoder,
            classifier,
            criterion,
            train_loader,
            optimizer,
            device,
            cfg["training"]["grad_clip"],
            cfg["training"]["log"],
            epoch,
            writer,
            global_step,
            train=True,
        )
        val_loss, val_acc, global_step = run_epoch(
            encoder,
            classifier,
            criterion,
            val_loader,
            optimizer,
            device,
            cfg["training"]["grad_clip"],
            cfg["training"]["log"],
            epoch,
            writer,
            global_step,
            train=False,
        )
        scheduler.step()
        dt = time.time() - t0

        LOGGER.info(
            "Epoch %03d/%03d summary | train_loss=%.4f | train_acc=%.4f | "
            "val_loss=%.4f | val_acc=%.4f | lr=%.8f | duration=%.1fs",
            epoch,
            cfg["training"]["num_epochs"],
            train_loss,
            train_acc,
            val_loss,
            val_acc,
            optimizer.param_groups[0]["lr"],
            dt,
        )
        if writer is not None:
            writer.add_scalar("epoch/train_loss", train_loss, epoch)
            writer.add_scalar("epoch/train_accuracy", train_acc, epoch)
            writer.add_scalar("epoch/validation_loss", val_loss, epoch)
            writer.add_scalar("epoch/validation_accuracy", val_acc, epoch)
            writer.add_scalar(
                "epoch/learning_rate", optimizer.param_groups[0]["lr"], epoch
            )
            writer.flush()

        # Periodic verification eval (EER/minDCF). This embeds every trial
        # utterance and is much more expensive than a training/validation
        # batch pass, so it only runs every `eval_every_n_epochs` epochs
        # (<=0 disables it entirely; the model still gets a final verification
        # eval after the training loop below).
        if eval_every_n_epochs > 0 and epoch % eval_every_n_epochs == 0:
            LOGGER.info("Periodic verification eval | epoch=%d", epoch)
            periodic_metrics = evaluate_verification(
                encoder,
                val_set,
                cfg["evaluation"]["verification_trial_list"],
                device,
                cfg["evaluation"],
            )
            LOGGER.info(
                "Epoch %03d verification | EER=%.4f%% | minDCF=%.6f | normalized_minDCF=%.4f",
                epoch,
                periodic_metrics["eer"] * 100,
                periodic_metrics["min_dcf"],
                periodic_metrics["normalized_min_dcf"],
            )
            if writer is not None:
                writer.add_scalar("epoch/eer", periodic_metrics["eer"], epoch)
                writer.add_scalar("epoch/min_dcf", periodic_metrics["min_dcf"], epoch)
                writer.add_scalar(
                    "epoch/normalized_min_dcf",
                    periodic_metrics["normalized_min_dcf"],
                    epoch,
                )
                writer.flush()
            # evaluate_verification() leaves the encoder in eval mode; the next
            # call to run_epoch() explicitly sets train/eval mode again, so no
            # manual restore is needed here.

        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_acc": train_acc,
                "val_loss": val_loss,
                "val_acc": val_acc,
            }
        )

        # --- Checkpoint management -------------------------------------
        # Save every epoch's checkpoint, then prune down to the `save_top_k`
        # checkpoints with the lowest val_loss (save_top_k<=0 keeps them all).
        # This bounds disk usage while still keeping a handful of good
        # checkpoints around (e.g. for ensembling or inspecting overfitting),
        # rather than only ever keeping a single "best" checkpoint.
        improved = val_loss < best_val_loss
        if improved:
            best_val_loss = val_loss
            bad_epochs = 0
        else:
            bad_epochs += 1

        epoch_ckpt_path = os.path.join(
            ckpt_dir, f"epoch{epoch:03d}_valloss{val_loss:.4f}.pt"
        )
        torch.save(
            {
                "encoder": encoder.state_dict(),
                "classifier": classifier.state_dict(),
                "speaker2idx": train_set.speaker2idx,
                "epoch": epoch,
                "val_loss": val_loss,
            },
            epoch_ckpt_path,
        )
        LOGGER.info(
            "Checkpoint saved | %s | val_loss=%.4f",
            os.path.basename(epoch_ckpt_path),
            val_loss,
        )
        top_checkpoints.append((val_loss, epoch_ckpt_path))
        top_checkpoints.sort(key=lambda item: item[0])
        if save_top_k > 0:
            while len(top_checkpoints) > save_top_k:
                _, stale_path = top_checkpoints.pop()
                if os.path.exists(stale_path):
                    os.remove(stale_path)
                LOGGER.info(
                    "Checkpoint pruned (outside top-%d by val_loss) | %s",
                    save_top_k,
                    os.path.basename(stale_path),
                )

        if improved:
            shutil.copyfile(epoch_ckpt_path, os.path.join(ckpt_dir, "best_model.pt"))
            LOGGER.info(
                "best_model.pt updated | epoch=%d | val_loss=%.4f", epoch, val_loss
            )
        else:
            if bad_epochs >= patience:
                LOGGER.info(
                    "Early stopping | epoch=%d | val_loss did not improve for %d epochs",
                    epoch,
                    patience,
                )
                break

    # Save the train/validation history for plotting curves in the report.
    import json

    with open(os.path.join(ckpt_dir, "history.json"), "w") as f:
        json.dump(history, f, indent=2)
    LOGGER.info("Training history saved | %s", os.path.join(ckpt_dir, "history.json"))

    LOGGER.info(
        "Verification evaluation started | verification_trial_list=%s",
        cfg["evaluation"]["verification_trial_list"],
    )
    verification_metrics = evaluate_verification(
        encoder,
        val_set,
        cfg["evaluation"]["verification_trial_list"],
        device,
        cfg["evaluation"],
    )
    LOGGER.info(
        "Verification evaluation completed | EER=%.4f%% | minDCF=%.6f | normalized_minDCF=%.4f",
        verification_metrics["eer"] * 100,
        verification_metrics["min_dcf"],
        verification_metrics["normalized_min_dcf"],
    )
    if writer is not None:
        writer.add_scalar("evaluation/eer", verification_metrics["eer"], global_step)
        writer.add_scalar(
            "evaluation/min_dcf", verification_metrics["min_dcf"], global_step
        )
        writer.add_scalar(
            "evaluation/normalized_min_dcf",
            verification_metrics["normalized_min_dcf"],
            global_step,
        )
        writer.close()
        LOGGER.info("TensorBoard logging completed | %s", cfg["training"]["log_dir"])


if __name__ == "__main__":
    main()
