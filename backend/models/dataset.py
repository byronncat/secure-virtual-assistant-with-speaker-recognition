"""
dataset.py
==========
Dataset / DataLoader for the speaker verification task.
Reads the CSV manifest (utt_id, speaker_id, file_path, duration, split),
loads audio, resamples it to the standard sample rate, crops/pads it to
max_duration during training, and extracts Mel-filterbank (fbank) features.
"""

import random

import pandas as pd
import torch
import torchaudio
from torch.utils.data import Dataset


class SpeakerDataset(Dataset):
    def __init__(
        self,
        manifest_path,
        sample_rate=16000,
        max_duration=8.0,
        n_mels=80,
        n_fft=400,
        win_length=400,
        hop_length=160,
        train_mode=True,
        speaker2idx=None,
        min_duration=0.0,
        augment=False,
        freq_mask_param=0,
        time_mask_param=0,
        num_freq_masks=0,
        num_time_masks=0,
        gain_db_range=(0.0, 0.0),
        gain_prob=0.0,
    ):
        self.df = pd.read_csv(manifest_path)
        # Manifests record duration during preparation.  Filtering here makes
        # the training configuration authoritative even for old manifests.
        if min_duration > 0:
            self.df = self.df[self.df["duration"] >= min_duration].reset_index(
                drop=True
            )
        self.sample_rate = sample_rate
        self.max_samples = int(max_duration * sample_rate)
        self.train_mode = train_mode

        # --- Data augmentation (train_mode only; never applied for eval) ---
        # `augment` gates everything below so validation/test datasets can be
        # constructed with train_mode=True (for fixed-length batching) while
        # still receiving no augmentation, by simply leaving augment=False.
        self.augment = augment and train_mode
        self.num_freq_masks = num_freq_masks
        self.num_time_masks = num_time_masks
        self.gain_db_range = gain_db_range
        self.gain_prob = gain_prob
        self.freq_masking = (
            torchaudio.transforms.FrequencyMasking(freq_mask_param)
            if self.augment and freq_mask_param > 0 and num_freq_masks > 0
            else None
        )
        self.time_masking = (
            torchaudio.transforms.TimeMasking(time_mask_param)
            if self.augment and time_mask_param > 0 and num_time_masks > 0
            else None
        )

        if speaker2idx is None:
            speakers = sorted(self.df["speaker_id"].unique().tolist())
            self.speaker2idx = {s: i for i, s in enumerate(speakers)}
        else:
            self.speaker2idx = speaker2idx

        self.feat_extractor = torchaudio.transforms.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=n_fft,
            win_length=win_length,
            hop_length=hop_length,
            n_mels=n_mels,
        )
        self.to_db = torchaudio.transforms.AmplitudeToDB()

    def __len__(self):
        return len(self.df)

    def _load_wave(self, path):
        wav, sr = torchaudio.load(path)
        if wav.shape[0] > 1:  # stereo -> mono
            wav = wav.mean(dim=0, keepdim=True)
        if sr != self.sample_rate:
            wav = torchaudio.functional.resample(wav, sr, self.sample_rate)
        wav = wav.squeeze(0)

        if self.augment and self.gain_prob > 0 and random.random() < self.gain_prob:
            wav = self._apply_random_gain(wav)

        if self.train_mode:
            # Use fixed-length random crops for batching, following ECAPA training.
            if wav.shape[0] >= self.max_samples:
                start = random.randint(0, wav.shape[0] - self.max_samples)
                wav = wav[start : start + self.max_samples]
            else:
                pad = self.max_samples - wav.shape[0]
                wav = torch.nn.functional.pad(wav, (0, pad))
        return wav

    def _apply_random_gain(self, wav):
        """Scale the waveform by a random gain (in dB), sampled uniformly
        from `gain_db_range`. Cheap channel/loudness perturbation that helps
        the model generalize across recording conditions."""
        low, high = self.gain_db_range
        gain_db = random.uniform(low, high)
        gain_factor = 10 ** (gain_db / 20.0)
        return wav * gain_factor

    def _apply_specaugment(self, feat):
        """Apply SpecAugment (frequency + time masking) to a (n_mels, T)
        log-mel spectrogram. Only used for training utterances."""
        if self.freq_masking is not None:
            for _ in range(self.num_freq_masks):
                feat = self.freq_masking(feat)
        if self.time_masking is not None:
            for _ in range(self.num_time_masks):
                feat = self.time_masking(feat)
        return feat

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        wav = self._load_wave(row["file_path"])
        feat = self.to_db(self.feat_extractor(wav.unsqueeze(0))).squeeze(
            0
        )  # (n_mels, T)
        if self.augment:
            feat = self._apply_specaugment(feat)
        feat = feat.transpose(0, 1)  # (T, n_mels)  -- SpeechBrain convention
        label = self.speaker2idx[row["speaker_id"]]
        return feat, label

    def extract_features_full(self, path):
        """Use during evaluation: do not crop; use the entire utterance."""
        wav, sr = torchaudio.load(path)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != self.sample_rate:
            wav = torchaudio.functional.resample(wav, sr, self.sample_rate)
        feat = self.to_db(self.feat_extractor(wav)).squeeze(0).transpose(0, 1)
        return feat


def collate_fn(batch):
    feats, labels = zip(*batch)
    feats = torch.stack(
        feats, dim=0
    )  # (B, T, n_mels) -- same length due to random cropping
    labels = torch.tensor(labels, dtype=torch.long)
    return feats, labels
