// Small shared pieces of the interface: the brand mark, icons, and the touch-friendly controls.
import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";

type IconProps = { size?: number };
const svg = (size: number, children: ReactNode) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

export const Icon = {
  printer: ({ size = 24 }: IconProps) => svg(size, <><path d="M6 9V3h12v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><path d="M6 14h12v7H6z" /></>),
  check: ({ size = 24 }: IconProps) => svg(size, <path d="M5 12.5l4.5 4.5L19 7.5" />),
  clock: ({ size = 24 }: IconProps) => svg(size, <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
  file: ({ size = 24 }: IconProps) => svg(size, <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></>),
  upload: ({ size = 24 }: IconProps) => svg(size, <><path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></>),
  alert: ({ size = 24 }: IconProps) => svg(size, <><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4" /><path d="M12 17.5v.5" /></>),
  x: ({ size = 24 }: IconProps) => svg(size, <path d="M6 6l12 12M18 6L6 18" />),
  copy: ({ size = 24 }: IconProps) => svg(size, <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>),
  monitor: ({ size = 24 }: IconProps) => svg(size, <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>),
  qr: ({ size = 24 }: IconProps) => svg(size, <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><path d="M14 14h2v2h-2zM18 18h2v2h-2zM18 14h2M14 18v2" /></>),
  arrow: ({ size = 24 }: IconProps) => svg(size, <path d="M5 12h14M13 6l6 6-6 6" />),
};

/** The brand mark at the top of every page; it leads home. */
export function TopBar({ to = "/", children }: { to?: string; children?: ReactNode }) {
  return (
    <nav className="topbar">
      <Link to={to} className="brand" aria-label="AutoPrint home"><span className="brand-mark"><Icon.printer size={18} /></span>AutoPrint</Link>
      {children}
    </nav>
  );
}

/** Two or three choices side by side, as large touch targets. Real radio buttons underneath. */
export function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: { value: T; label: string; hint?: string }[]; onChange: (v: T) => void;
}) {
  const name = useId();
  return (
    <div className="field" role="radiogroup" aria-label={label}>
      <span className="field-label">{label}</span>
      <div className="seg">
        {options.map((o) => (
          <label key={o.value} className={o.value === value ? "on" : ""}>
            <input type="radio" name={name} checked={o.value === value} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
            {o.hint && <small>{o.hint}</small>}
          </label>
        ))}
      </div>
    </div>
  );
}

/** A number with big minus and plus buttons; typing still works. */
export function Stepper({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  const clamp = (n: number) => Math.max(min, Math.min(max, n));
  const safe = Number.isFinite(value) ? value : min;
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="stepper">
        <button type="button" aria-label={`Fewer ${label.toLowerCase()}`} disabled={safe <= min} onClick={() => onChange(clamp(safe - 1))}>−</button>
        <input type="number" inputMode="numeric" aria-label={label} min={min} max={max} value={Number.isFinite(value) ? value : ""}
               onChange={(e) => onChange(Math.trunc(Number(e.target.value)))} />
        <button type="button" aria-label={`More ${label.toLowerCase()}`} disabled={safe >= max} onClick={() => onChange(clamp(safe + 1))}>+</button>
      </div>
    </div>
  );
}

/** Where the customer is in a short flow: numbered dots joined by a line. */
export function Steps({ labels, current }: { labels: string[]; current: number }) {
  return (
    <ol className="steps" aria-label="Progress">
      {labels.map((l, i) => {
        const n = i + 1;
        const state = n < current ? "done" : n === current ? "now" : "todo";
        return <li key={l} className={state} aria-current={state === "now" ? "step" : undefined}><i>{state === "done" ? <Icon.check size={14} /> : n}</i><span>{l}</span></li>;
      })}
    </ol>
  );
}

/** "just now", "5 min ago", "3 h ago", then the date. */
export function timeAgo(iso: string, now = Date.now()): string {
  const secs = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} h ago`;
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

export function fileSize(bytes: number): string {
  return bytes < 1_048_576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1_048_576).toFixed(1)} MB`;
}
