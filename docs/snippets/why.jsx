// A short first-person note on why something was built the way it was.
export const Why = ({ title = "Why it works this way", children }) => (
  <aside className="bss-why">
    <p className="bss-why-title">{title}</p>
    <div className="bss-why-body">{children}</div>
  </aside>
);
