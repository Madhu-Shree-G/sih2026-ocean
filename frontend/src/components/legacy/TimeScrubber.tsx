import { useEffect } from "react";
import { Pause, Play, SkipBack } from "lucide-react";
import { useAppStore } from "@/state/store";
import { formatDate, formatUtc } from "@/lib/format";
import "./TimeScrubber.css";

interface TimeScrubberProps {
  times: string[];
}

const RATES = [0.5, 1, 2, 4];

export function TimeScrubber({ times }: TimeScrubberProps) {
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

  /* Advance the clock while playing. The interval is derived from the rate so
     changing speed takes effect immediately rather than on the next tick. */
  useEffect(() => {
    if (!playing || times.length < 2) return;
    const interval = window.setInterval(() => {
      const next = useAppStore.getState().timeIndex + 1;
      setTimeIndex(next > last ? 0 : next);
    }, 900 / playbackRate);
    return () => window.clearInterval(interval);
  }, [playing, playbackRate, last, times.length, setTimeIndex]);

  /* Space plays and pauses, arrows step - the shortcuts a forecaster expects. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;

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

  const progress = last > 0 ? (current / last) * 100 : 0;

  return (
    <div className="scrub">
      <button
        className="scrub__play"
        type="button"
        onClick={togglePlaying}
        aria-label={playing ? "Pause" : "Play"}
        title={playing ? "Pause (Space)" : "Play (Space)"}
      >
        {playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" />}
      </button>

      <button
        className="scrub__skip"
        type="button"
        onClick={() => {
          setPlaying(false);
          setTimeIndex(0);
        }}
        aria-label="Jump to start"
        title="Jump to start"
      >
        <SkipBack size={16} />
      </button>

      <div className="scrub__track">
        <div className="scrub__labels">
          <span>{formatDate(times[0])}</span>
          <span className="scrub__now mono">{formatUtc(times[current])}</span>
          <span>{formatDate(times[last])}</span>
        </div>

        <div className="scrub__rail">
          <div className="scrub__fill" style={{ width: `${progress}%` }} />
          <div className="scrub__ticks" aria-hidden>
            {times.map((_, index) => (
              <span
                key={index}
                className={index === current ? "is-current" : undefined}
                style={{ left: `${last > 0 ? (index / last) * 100 : 0}%` }}
              />
            ))}
          </div>
          <input
            className="scrub__input"
            type="range"
            min={0}
            max={last}
            step={1}
            value={current}
            onChange={(event) => {
              setPlaying(false);
              setTimeIndex(Number(event.target.value));
            }}
            aria-label="Timestep"
            aria-valuetext={formatUtc(times[current])}
          />
        </div>
      </div>

      <select
        className="scrub__rate"
        value={playbackRate}
        onChange={(event) => setPlaybackRate(Number(event.target.value))}
        aria-label="Playback speed"
      >
        {RATES.map((rate) => (
          <option key={rate} value={rate}>
            {rate}x
          </option>
        ))}
      </select>
    </div>
  );
}
