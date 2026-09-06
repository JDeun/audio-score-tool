from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .native_events import BOS, EOS, PAD, VOCAB_SIZE


@dataclass(slots=True)
class NativeModelConfig:
    sample_rate: int = 16_000
    n_mels: int = 128
    n_fft: int = 1024
    hop_length: int = 320
    d_model: int = 384
    nhead: int = 8
    encoder_layers: int = 8
    decoder_layers: int = 6
    dim_feedforward: int = 1536
    dropout: float = 0.1
    max_audio_frames: int = 12_000
    max_tokens: int = 4096


def require_torch():
    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:  # pragma: no cover - exercised only without optional runtime
        raise RuntimeError(
            "AudioScore Native requires the optional native dependencies. "
            "Install with `uv sync --extra native`."
        ) from exc
    return torch, nn


def build_model(config: NativeModelConfig):
    torch, nn = require_torch()

    class AudioScoreNativeModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.config = config
            self.audio_projection = nn.Sequential(
                nn.Conv1d(config.n_mels, config.d_model, kernel_size=5, stride=2, padding=2),
                nn.GELU(),
                nn.Conv1d(config.d_model, config.d_model, kernel_size=3, stride=2, padding=1),
                nn.GELU(),
            )
            self.audio_position = nn.Embedding(config.max_audio_frames, config.d_model)
            self.token_embedding = nn.Embedding(VOCAB_SIZE, config.d_model, padding_idx=PAD)
            self.token_position = nn.Embedding(config.max_tokens, config.d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=config.d_model,
                nhead=config.nhead,
                dim_feedforward=config.dim_feedforward,
                dropout=config.dropout,
                batch_first=True,
                norm_first=True,
            )
            decoder_layer = nn.TransformerDecoderLayer(
                d_model=config.d_model,
                nhead=config.nhead,
                dim_feedforward=config.dim_feedforward,
                dropout=config.dropout,
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=config.encoder_layers)
            self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=config.decoder_layers)
            self.output = nn.Linear(config.d_model, VOCAB_SIZE)

        def encode(self, mel):
            hidden = self.audio_projection(mel).transpose(1, 2)
            frames = hidden.shape[1]
            if frames > config.max_audio_frames:
                hidden = hidden[:, : config.max_audio_frames]
                frames = config.max_audio_frames
            positions = torch.arange(frames, device=hidden.device).unsqueeze(0)
            hidden = hidden + self.audio_position(positions)
            return self.encoder(hidden)

        def decode(self, tokens, memory):
            length = tokens.shape[1]
            positions = torch.arange(length, device=tokens.device).unsqueeze(0)
            hidden = self.token_embedding(tokens) + self.token_position(positions)
            causal = torch.triu(
                torch.full((length, length), float("-inf"), device=tokens.device),
                diagonal=1,
            )
            hidden = self.decoder(hidden, memory, tgt_mask=causal)
            return self.output(hidden)

        def forward(self, mel, tokens):
            return self.decode(tokens, self.encode(mel))

        @torch.inference_mode()
        def generate(self, mel, max_tokens: int | None = None):
            self.eval()
            memory = self.encode(mel)
            limit = min(max_tokens or config.max_tokens, config.max_tokens)
            tokens = torch.full((mel.shape[0], 1), BOS, dtype=torch.long, device=mel.device)
            finished = torch.zeros(mel.shape[0], dtype=torch.bool, device=mel.device)
            for _ in range(limit - 1):
                logits = self.decode(tokens, memory)[:, -1]
                next_token = logits.argmax(dim=-1)
                tokens = torch.cat([tokens, next_token[:, None]], dim=1)
                finished |= next_token.eq(EOS)
                if bool(finished.all()):
                    break
            return tokens

    return AudioScoreNativeModel()


def save_checkpoint(path: Path, model, config: NativeModelConfig, **metadata) -> None:
    torch, _nn = require_torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "format": "audio-score-native-v1",
            "config": config.__dict__,
            "state_dict": model.state_dict(),
            "metadata": metadata,
        },
        path,
    )


def load_checkpoint(path: Path, device: str = "cpu"):
    torch, _nn = require_torch()
    payload = torch.load(path, map_location=device, weights_only=False)
    if payload.get("format") != "audio-score-native-v1":
        raise RuntimeError("Unsupported AudioScore Native checkpoint format.")
    config = NativeModelConfig(**payload["config"])
    model = build_model(config)
    model.load_state_dict(payload["state_dict"])
    model.to(device)
    model.eval()
    return model, config, payload.get("metadata", {})
