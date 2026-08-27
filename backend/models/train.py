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
import time

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
    LOGGER.info("Dataset initialization | manifest_dir=%s", manifest_dir)
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
    )
    LOGGER.info(
        "Datasets ready | train_samples=%d | val_samples=%d | speakers=%d | min_duration=%.2fs",
        len(train_set),
        len(val_set),
        len(train_set.speaker2idx),
        cfg["data"]["min_duration"],
    )

    train_loader = DataLoader(
        train_set,
        batch_size=cfg["training"]["batch_size"],
        shuffle=True,
        num_workers=cfg["training"]["num_workers"],
        collate_fn=collate_fn,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_set,
        batch_size=cfg["training"]["batch_size"],
        shuffle=False,
        num_workers=cfg["training"]["num_workers"],
        collate_fn=collate_fn,
    )
    LOGGER.info(
        "Data loaders ready | batch_size=%d | workers=%d | train_batches=%d | val_batches=%d",
        cfg["training"]["batch_size"],
        cfg["training"]["num_workers"],
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

        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_acc": train_acc,
                "val_loss": val_loss,
                "val_acc": val_acc,
            }
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            bad_epochs = 0
            torch.save(
                {
                    "encoder": encoder.state_dict(),
                    "classifier": classifier.state_dict(),
                    "speaker2idx": train_set.speaker2idx,
                    "epoch": epoch,
                },
                os.path.join(ckpt_dir, "best_model.pt"),
            )
            LOGGER.info("Checkpoint saved | best_model.pt | val_loss=%.4f", val_loss)
        else:
            bad_epochs += 1
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
        "Verification evaluation started | trial_list=%s",
        cfg["evaluation"]["trial_list"],
    )
    verification_metrics = evaluate_verification(
        encoder, val_set, cfg["evaluation"]["trial_list"], device, cfg["evaluation"]
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
