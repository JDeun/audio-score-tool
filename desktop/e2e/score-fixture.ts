import { createHash } from "node:crypto";

export function scoreSha256(xml: string) {
  return createHash("sha256").update(xml).digest("hex");
}

export function scoreSnapshot<T>(song: T, xml: string) {
  return { song, score_sha256: scoreSha256(xml) };
}
