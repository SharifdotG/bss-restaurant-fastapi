// The dashboard's status pill. Tones: amber, orange, green, slate, red.
export const Pill = ({ tone = "slate", children }) => (
  <span className={`bss-pill bss-pill-${tone}`}>{children}</span>
);
