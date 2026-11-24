import { useId } from "react";

type Frame = { index: number; time_seconds: number; raw_hz: number; hz: number; periodicity: number; loudness_db_a: number };
export type PitchWindow = { source_id: string; start_frame: number; end_frame_exclusive: number;
  note_frame_start: number; note_frame_end_exclusive: number; frames: Frame[] };
const object = (value: unknown): value is Record<string, any> => typeof value === "object" && value !== null && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);

export function parsePitchObservation(value: unknown, generation: unknown, expected: number | null, sourceIds: unknown[]):
  { windows?: Map<string, PitchWindow>; message?: string } {
  if (value === undefined) return {};
  const invalid = { message: "음높이 관측 형식을 확인할 수 없어 그래프를 표시하지 않습니다." };
  if (!object(value) || value.schema_version !== 1 || generation !== expected || expected === null) return invalid;
  if (value.status === "unavailable") {
    if (typeof value.reason !== "string") return invalid;
    const reasons: Record<string, string> = { unavailable: "보존된 관측이 없습니다", no_source: "연결된 원본이 없습니다",
      limit_exceeded: "표시 가능한 관측 범위를 초과했습니다", invalid: "보존된 관측을 확인할 수 없습니다",
      empty_interval: "원본 음표의 관측 구간이 비어 있습니다" };
    return { message: `분리 보컬 음높이 관측을 표시하지 않습니다: ${reasons[value.reason] ?? "지원하지 않는 상태입니다"}.` };
  }
  if (value.status !== "available" || value.frame_clock !== "stem_local" || value.advisory !== true
      || value.algorithm !== "tiny-frame-window-v1" || value.frame_interval_seconds !== .01
      || !hash(value.pitch_sha256) || !hash(value.stem_sha256) || !hash(value.pitch_runtime_sha256)
      || !object(value.thresholds) || value.thresholds.periodicity !== .21 || value.thresholds.loudness_db_a !== -60
      || !object(value.acoustic_onset) || value.acoustic_onset.status !== "not_measured"
      || !object(value.perceptual_onset) || value.perceptual_onset.status !== "not_measured"
      || !Array.isArray(value.sources) || value.sources.length < 1 || value.sources.length > 16
      || sourceIds.some(id => typeof id !== "string") || new Set(sourceIds).size !== sourceIds.length
      || value.sources.length !== sourceIds.length) return invalid;
  const windows = new Map<string, PitchWindow>();
  for (const source of value.sources) {
    if (!object(source) || typeof source.source_id !== "string" || !sourceIds.includes(source.source_id)
        || windows.has(source.source_id) || !integer(source.start_frame) || !integer(source.end_frame_exclusive)
        || !integer(source.note_frame_start) || !integer(source.note_frame_end_exclusive)
        || source.start_frame > source.note_frame_start || source.note_frame_start >= source.note_frame_end_exclusive
        || source.note_frame_end_exclusive > source.end_frame_exclusive || !Array.isArray(source.frames)
        || source.frames.length < 1 || source.frames.length > 1201
        || source.frames.length !== source.end_frame_exclusive - source.start_frame || !Array.isArray(source.gate_transitions)) return invalid;
    for (let i = 0; i < source.frames.length; i++) {
      const frame = source.frames[i];
      if (!object(frame) || frame.index !== source.start_frame + i || !finite(frame.time_seconds)
          || Math.abs(frame.time_seconds - frame.index * .01) > 1e-6 || !finite(frame.raw_hz) || frame.raw_hz <= 0
          || !finite(frame.hz) || !finite(frame.periodicity) || frame.periodicity < 0 || frame.periodicity > 1
          || !finite(frame.loudness_db_a)
          || (frame.hz !== 0 && frame.hz !== frame.raw_hz)) return invalid;
    }
    const expectedTransitions = source.frames.slice(1).flatMap((right: Frame, i: number) => {
      const left = source.frames[i];
      return (left.hz > 0) === (right.hz > 0) ? [] : [{ kind: right.hz > 0 ? "accepted" : "rejected",
        left_frame: left.index, right_frame: right.index, from_seconds: left.time_seconds, to_seconds: right.time_seconds }];
    });
    if (source.gate_transitions.length !== expectedTransitions.length || source.gate_transitions.some((t: unknown, i: number) =>
      !object(t) || Object.entries(expectedTransitions[i]).some(([key, val]) => t[key] !== val))) return invalid;
    windows.set(source.source_id, source as PitchWindow);
  }
  return { windows };
}

export default function PitchObservationPlot({ window, writtenMidi }: { window: PitchWindow; writtenMidi: number | null }) {
  const id = useId();
  const points = window.frames.filter(frame => frame.raw_hz > 0).map(frame => ({ ...frame, midi: 69 + 12 * Math.log2(frame.raw_hz / 440) }));
  const values = points.map(point => point.midi).concat(writtenMidi === null ? [] : [writtenMidi]);
  const low = values.length ? Math.floor(Math.min(...values) - 1) : 0;
  const high = values.length ? Math.ceil(Math.max(...values) + 1) : 1;
  const x = (index: number) => 38 + 246 * (index - window.start_frame) / window.frames.length;
  const y = (midi: number) => 100 - 80 * (midi - low) / (high - low);
  const accepted = points.filter(p => p.hz > 0).length;
  const pitchName = (midi: number) => {
    const rounded = Math.round(midi);
    const names = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
    return `${names[((rounded % 12) + 12) % 12]}${Math.floor(rounded / 12) - 1}`;
  };
  return <div className="pitch-observation" data-source-id={window.source_id}>
    <strong>분리 보컬 음높이 관측</strong>
    <p>분리 보컬 기준 상대 시간의 모델 관측이며 정확도는 확정되지 않았습니다. 원은 검출 조건 통과, 엑스는 제외된 관측입니다. 실제 음향·인지 시작 시각은 측정하지 않았습니다.</p>
    <svg viewBox="0 0 300 126" role="img" aria-labelledby={`${id}-title ${id}-desc`}>
      <title id={`${id}-title`}>분리 보컬 음높이 관측과 현재 기보 음높이</title>
      <desc id={`${id}-desc`}>세로축은 음 이름과 옥타브, 가로축은 분리 보컬 기준 초입니다. 강조 영역은 원본 모델 음표 구간이며, 원은 검출 조건 통과, 엑스는 제외된 관측, 점선은 현재 기보 음높이입니다.</desc>
      <rect x={x(window.note_frame_start)} y="20" width={x(window.note_frame_end_exclusive) - x(window.note_frame_start)} height="80" className="pitch-note-range" />
      <line x1="38" x2="284" y1="100" y2="100" className="pitch-axis" />
      <line x1="38" x2="38" y1="20" y2="100" className="pitch-axis" />
      <text x="0" y="12">음높이</text><text x="4" y="25">{pitchName(high)}</text><text x="4" y="103">{pitchName(low)}</text>
      {writtenMidi !== null && <line x1="38" x2="284" y1={y(writtenMidi)} y2={y(writtenMidi)} className="pitch-written" />}
      {points.map(p => p.hz > 0 ? <circle key={p.index} cx={x(p.index)} cy={y(p.midi)} r="1.7" className="pitch-accepted" />
        : <path key={p.index} d={`M${x(p.index)-2} ${y(p.midi)-2}l4 4m0 -4l-4 4`} className="pitch-rejected" />)}
      <text x="38" y="119">{window.frames[0].time_seconds.toFixed(2)}초</text>
      <text x="284" y="119" textAnchor="end">{(window.end_frame_exclusive * .01).toFixed(2)}초</text>
    </svg>
    <p>강조 범위는 원본 모델 음표 구간입니다 ({(window.note_frame_start * .01).toFixed(2)}초 이상, {(window.note_frame_end_exclusive * .01).toFixed(2)}초 미만). 현재 편집 음표의 실제 발성 경계가 아닙니다.</p>
    <p>통과 {accepted}개 · 제외 {window.frames.length - accepted}개{writtenMidi !== null && ` · 점선은 현재 기보 ${pitchName(writtenMidi)}`}</p>
  </div>;
}
