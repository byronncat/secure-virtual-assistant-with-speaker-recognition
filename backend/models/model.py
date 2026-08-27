"""
model.py
========
Builds an ECAPA-TDNN model (an embedding encoder) and a classifier head
using AAM-Softmax (Additive Angular Margin Softmax, similar to ArcFace)
for speaker classification. The penultimate-layer embedding is then used
as the speaker vector for verification (cosine-similarity matching).

Uses SpeechBrain's existing building blocks directly.
"""

import sys

import speechbrain
import torch
import torch.nn as nn
import torch.nn.functional as F

from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN
from speechbrain.nnet.losses import LogSoftmaxWrapper, AdditiveAngularMargin

# SpeechBrain 1.1 registers legacy, lazily-loaded optional integrations at
# import time. On Windows, PyTorch's optimizer introspection can accidentally
# load them because SpeechBrain's inspect-path guard expects POSIX separators.
# This project uses none of the deprecated aliases, so remove their redirects.
for _legacy_module in (
    "speechbrain.pretrained",
    "speechbrain.nnet.loss.transducer_loss",
    *speechbrain.deprecations,
):
    sys.modules.pop(_legacy_module, None)


class ECAPAModel(nn.Module):
    """Encoder ECAPA-TDNN -> speaker embedding (192 dimensions by default)."""

    def __init__(
        self,
        input_size=80,
        lin_neurons=192,
        channels=(512, 512, 512, 512, 1536),
        kernel_sizes=(5, 3, 3, 3, 1),
        dilations=(1, 2, 3, 4, 1),
        attention_channels=128,
    ):
        super().__init__()
        self.encoder = ECAPA_TDNN(
            input_size=input_size,
            channels=list(channels),
            kernel_sizes=list(kernel_sizes),
            dilations=list(dilations),
            attention_channels=attention_channels,
            lin_neurons=lin_neurons,
        )

    def forward(self, feats):
        # feats: (B, T, n_mels)  ->  embedding: (B, lin_neurons)
        emb = self.encoder(feats)  # (B, 1, lin_neurons)
        return emb.squeeze(1)


class SpeakerClassifier(nn.Module):
    """Speaker-classification head used during training (AAM-Softmax)."""

    def __init__(self, emb_dim, num_speakers):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(num_speakers, emb_dim))
        nn.init.xavier_uniform_(self.weight)

    def forward(self, emb):
        emb = F.normalize(emb, dim=-1)
        w = F.normalize(self.weight, dim=-1)
        cosine = F.linear(emb, w)  # (B, num_speakers)
        return cosine


def build_model_and_loss(config, num_speakers):
    m = config["model"]
    encoder = ECAPAModel(
        input_size=m["input_size"],
        lin_neurons=m["lin_neurons"],
        channels=m["channels"],
        kernel_sizes=m["kernel_sizes"],
        dilations=m["dilations"],
        attention_channels=m["attention_channels"],
    )
    classifier = SpeakerClassifier(m["lin_neurons"], num_speakers)

    loss_cfg = config["loss"]
    if loss_cfg["type"].lower() != "aam_softmax":
        raise ValueError(
            "Unsupported loss.type. This model currently supports 'aam_softmax'."
        )
    aam = AdditiveAngularMargin(margin=loss_cfg["margin"], scale=loss_cfg["scale"])
    criterion = LogSoftmaxWrapper(loss_fn=aam)
    return encoder, classifier, criterion
