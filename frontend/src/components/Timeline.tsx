/**
 * The time control.
 *
 * Keyboard shortcuts stay (space to play, arrows to step) but they now check
 * that the event did not come from a text field, and the control announces the
 * step it is on so a screen reader user hears the date rather than "7 of 14".
 */

import { useEffect } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useAppStore } from "@/state/store";
import { formatDate, formatUtc } from "@/lib/format";
import { IconButton } from "@/ui";

const RATES = [0.5, 1, 2, 4];
const BASE_INTERVAL_MS = 900;

export function Timeline({ times }: { times: string[] }) {
  const {
    timeIndex,
    setTimeIndex,
    playing,
    togglePlaying,
    setPlaying,
    playbackRate,
    setPlaybackRate,
  } = useAppStore();

  const last = Math.max(0, times.length - 1);
  const current = Math.min(timeIndex, last);

  /* Advance while playing. The interval is derived from the rate so a speed
     change takes effect immediately rather than after the current tick. */
  useEffect(() => {
    if (!playing || times.length < 2) return;
    const id = window.setInterval(() => {
      const next = useAppStore.getState().timeIndex + 1;
      setTimeIndex(next > last ? 0 : next);
    }, BASE_INTERVAL_MS / playbackRate);
    return () => window.clearInterval(id);
  }, [playing, playbackRate, last, times.length, setTimeIndex]);

  /* Space plays and pauses, arrows step. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
      if (target?.isContentEditable) return;

      if (event.code === "Space") {
        event.preventDefault();
        togglePlaying();
      } else if (event.code === "ArrowRight") {
        event.preventDefault();
        setPlaying(false);
        setTimeIndex(Math.min(last, useAppStore.getState().timeIndex + 1));
      } else if (event.code === "ArrowLeft") {
        event.preventDefault();
        setPlaying(false);
        setTimeIndex(Math.max(0, useAppStore.getState().timeIndex - 1));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [last, setTimeIndex, setPlaying, togglePlaying]);

  const step = (delta: number) => {
    setPlaying(false);
    setTimeIndex(Math.max(0, Math.min(last, current + delta)));
  };

  if (times.length === 0) return null;

  return (
    <div className="timeline">
      <IconButton
        icon={<SkipBack size={17} />}
        label="Previous step (left arrow)"
        onClick={() => step(-1)}
        disabled={current === 0}
      />
      <IconButton
        icon={playing ? <Pause size={19} /> : <Play size={19} />}
        label={playing ? "Pause (space)" : "Play (space)"}
        bordered
        large
        onClick={togglePlaying}
        disabled={times.length < 2}
      />
      <IconButton
        icon={<SkipForward size={17} />}
        label="Next step (right arrow)"
        onClick={() => step(1)}
        disabled={current === last}
      />

      <div className="timeline__track">
        <div className="timeline__labels">
          <span>{formatDate(times[0])}</span>
          <span className="timeline__now mono">{formatUtc(times[current])}</span>
          <span>{formatDate(times[last])}</span>
        </div>
        <input
          type="range"
          min={0}
          max={last}
          step={1}
          value={current}
          onChange={(event) => {
            setPlaying(false);
            setTimeIndex(Number(event.target.value));
          }}
          aria-label="Time step"
          aria-valuetext={formatUtc(times[current])}
        />
      </div>

      <select
        className="control timeline__rate"
        value={playbackRate}
        onChange={(event) => setPlaybackRate(Number(event.target.value))}
        aria-label="Playback speed"
      >
        {RATES.map((rate) => (
          <option key={rate} value={rate}>
            {rate}×
          </option>
        ))}
      </select>
    </div>
  );
}
