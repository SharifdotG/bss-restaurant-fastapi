// A table of colour tokens with their light and dark values side by side.
export const Swatches = ({ rows }) => (
  <div className="bss-swatches">
    {rows.map(({ token, light, dark, use }) => (
      <div className="bss-swatch-row" key={token}>
        <span className="bss-swatch-pair" aria-hidden="true">
          <span className="bss-swatch" style={{ background: light }} />
          <span className="bss-swatch" style={{ background: dark }} />
        </span>
        <span className="bss-swatch-text">
          <code>--{token}</code>
          <span className="bss-swatch-use">{use}</span>
        </span>
        <span className="bss-swatch-values">
          {light}
          <br />
          {dark}
        </span>
      </div>
    ))}
  </div>
);
