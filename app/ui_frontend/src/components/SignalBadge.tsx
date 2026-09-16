import { C } from "../lib/theme";
type SignalKind = "BUY" | "SELL" | "HOLD";

const colors: Record<SignalKind, { bg: string; color: string; border: string }> = {
  BUY:  { bg: C.successBg, color: C.success, border: C.successDeep },
  SELL: { bg: C.dangerBg, color: C.danger, border: "var(--c-dangerDeep)" },
  HOLD: { bg: C.warningBg, color: C.warningSolid, border: C.warningDeep },
};

interface SignalBadgeProps { signal: SignalKind | string }

export default function SignalBadge({ signal }: SignalBadgeProps) {
  const style = colors[signal as SignalKind] || colors.HOLD;
  return (
    <span
      style={{
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: "0.75rem",
        fontWeight: 700,
        letterSpacing: "0.05em",
        border: `1px solid ${style.border}`,
        background: style.bg,
        color: style.color,
      }}
    >
      {signal}
    </span>
  );
}
