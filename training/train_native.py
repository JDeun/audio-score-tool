from __future__ import annotations

import argparse
import random
from pathlib import Path

from audio_score_tool.native_audio import load_log_mel
from audio_score_tool.native_events import PAD, midi_to_tokens
from audio_score_tool.native_model import (
    NativeModelConfig,
    build_model,
    require_torch,
    save_checkpoint,
)
from audio_score_tool.native_training import ALLOWED_TRAINING_LICENSES, load_manifest


def build_dataset(rows, config: NativeModelConfig, device: str = "cpu"):
    torch, _nn = require_torch()

    class ManifestDataset(torch.utils.data.Dataset):
        def __len__(self):
            return len(rows)

        def __getitem__(self, index):
            row = rows[index]
            mel = load_log_mel(Path(row["audio"]), config, device="cpu").squeeze(0)
            # Two stride-2 convolution layers reduce time by roughly 4x.
            mel = mel[:, : config.max_audio_frames * 4]
            tokens = midi_to_tokens(Path(row["midi"]), max_tokens=config.max_tokens)
            return mel, torch.tensor(tokens, dtype=torch.long)

    return ManifestDataset()


def collate_batch(batch):
    torch, _nn = require_torch()
    mels, tokens = zip(*batch)
    max_frames = max(mel.shape[-1] for mel in mels)
    max_tokens = max(token.shape[0] for token in tokens)
    mel_batch = torch.zeros(len(batch), mels[0].shape[0], max_frames, dtype=mels[0].dtype)
    token_batch = torch.full((len(batch), max_tokens), PAD, dtype=torch.long)
    for index, (mel, token) in enumerate(zip(mels, tokens, strict=True)):
        mel_batch[index, :, : mel.shape[-1]] = mel
        token_batch[index, : token.shape[0]] = token
    return mel_batch, token_batch


def evaluate(model, loader, device: str) -> float:
    torch, nn = require_torch()
    model.eval()
    loss_fn = nn.CrossEntropyLoss(ignore_index=PAD)
    total = 0.0
    count = 0
    with torch.inference_mode():
        for mel, tokens in loader:
            mel = mel.to(device)
            tokens = tokens.to(device)
            logits = model(mel, tokens[:, :-1])
            loss = loss_fn(logits.reshape(-1, logits.shape[-1]), tokens[:, 1:].reshape(-1))
            total += loss.item()
            count += 1
    return total / max(1, count)


def _resolve_device(torch, requested: str) -> str:
    requested = requested.lower()
    if requested.startswith("cuda"):
        return requested if torch.cuda.is_available() else "cpu"
    if requested == "mps":
        backend = getattr(torch.backends, "mps", None)
        return "mps" if backend is not None and backend.is_available() else "cpu"
    return "cpu"


def train(args) -> None:
    torch, nn = require_torch()
    config = NativeModelConfig(
        d_model=args.d_model,
        nhead=args.nhead,
        encoder_layers=args.encoder_layers,
        decoder_layers=args.decoder_layers,
        dim_feedforward=args.dim_feedforward,
        max_audio_frames=args.max_audio_frames,
        max_tokens=args.max_tokens,
    )
    train_rows = load_manifest(args.manifest, "train")
    val_rows = load_manifest(args.manifest, "validation")
    if not train_rows:
        raise ValueError("Manifest contains no training rows.")
    if not val_rows:
        if len(train_rows) < 2:
            raise ValueError(
                "A manifest without an explicit validation split needs at least two training rows."
            )
        # Keep the run usable for a small project-owned pilot manifest.
        random.Random(7).shuffle(train_rows)
        val_count = max(1, min(len(train_rows) // 10, 32))
        val_rows = train_rows[:val_count]
        train_rows = train_rows[val_count:]

    train_set = build_dataset(train_rows, config)
    val_set = build_dataset(val_rows, config)
    train_loader = torch.utils.data.DataLoader(
        train_set,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.workers,
        collate_fn=collate_batch,
    )
    val_loader = torch.utils.data.DataLoader(
        val_set,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.workers,
        collate_fn=collate_batch,
    )

    device = _resolve_device(torch, args.device)
    model = build_model(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
    loss_fn = nn.CrossEntropyLoss(ignore_index=PAD)
    best_val = float("inf")
    global_step = 0

    for epoch in range(1, args.epochs + 1):
        model.train()
        for mel, tokens in train_loader:
            mel = mel.to(device)
            tokens = tokens.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(mel, tokens[:, :-1])
            loss = loss_fn(logits.reshape(-1, logits.shape[-1]), tokens[:, 1:].reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            global_step += 1
            if global_step % args.log_every == 0:
                print(f"epoch={epoch} step={global_step} train_loss={loss.item():.4f}")

        val_loss = evaluate(model, val_loader, device)
        print(f"epoch={epoch} validation_loss={val_loss:.4f}")
        if val_loss < best_val:
            best_val = val_loss
            save_checkpoint(
                args.output,
                model,
                config,
                dataset="manifest-v1",
                manifest=str(args.manifest),
                validation_loss=val_loss,
                global_step=global_step,
                allowed_licenses=sorted(ALLOWED_TRAINING_LICENSES),
            )
            print(f"saved best checkpoint to {args.output}")


def parse_args():
    parser = argparse.ArgumentParser(description="Train AudioScore Native from an approved manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("checkpoints/audio-score-native.pt"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument("--d-model", type=int, default=384)
    parser.add_argument("--nhead", type=int, default=8)
    parser.add_argument("--encoder-layers", type=int, default=8)
    parser.add_argument("--decoder-layers", type=int, default=6)
    parser.add_argument("--dim-feedforward", type=int, default=1536)
    parser.add_argument("--max-audio-frames", type=int, default=12000)
    parser.add_argument("--max-tokens", type=int, default=4096)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
