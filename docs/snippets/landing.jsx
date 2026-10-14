// Pieces for the landing page: an intro block and a panel of links that reads like the dashboard's nav.
export const Intro = ({ title, children, actions }) => (
  <section className="bss-intro">
    <h1 className="bss-intro-title">{title}</h1>
    <div className="bss-intro-lead">{children}</div>
    {actions && <div className="bss-intro-actions">{actions}</div>}
  </section>
);

export const Action = ({ href, primary, children }) => (
  <a className={primary ? "bss-action bss-action-primary" : "bss-action"} href={href}>
    {children}
  </a>
);

export const LinkPanel = ({ title, children }) => (
  <section className="bss-panel">
    {title && <h2 className="bss-panel-title">{title}</h2>}
    <div className="bss-panel-rows">{children}</div>
  </section>
);

export const LinkRow = ({ href, icon, title, children }) => (
  <a className="bss-row" href={href}>
    <span className="bss-row-tile" aria-hidden="true">
      <img src={icon} alt="" />
    </span>
    <span className="bss-row-text">
      <span className="bss-row-title">{title}</span>
      <span className="bss-row-note">{children}</span>
    </span>
    <svg className="bss-row-arrow" viewBox="0 0 256 256" aria-hidden="true">
      <path d="M181.66,133.66l-72,72a8,8,0,0,1-11.32-11.32L164.69,128,98.34,61.66a8,8,0,0,1,11.32-11.32l72,72A8,8,0,0,1,181.66,133.66Z" />
    </svg>
  </a>
);
