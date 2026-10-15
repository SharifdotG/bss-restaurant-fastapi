// A dashboard screenshot that follows the docs theme. Files live in /images/screens as
// <name>.webp and <name>-dark.webp; phone shots add -phone. Kitchen is dark only.
export const Shot = ({ name, alt, phone, darkOnly, caption }) => {
  const file = `/images/screens/${name}${phone ? "-phone" : ""}`;
  return (
    <figure className={phone ? "bss-figure bss-figure-phone" : "bss-figure"}>
      {darkOnly ? (
        <img className="bss-screen" src={`${file}.webp`} alt={alt} />
      ) : (
        <>
          <img className="bss-screen bss-screen-light" src={`${file}.webp`} alt={alt} />
          <img className="bss-screen bss-screen-dark" src={`${file}-dark.webp`} alt={alt} />
        </>
      )}
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
};

// Phone screenshots side by side.
export const Phones = ({ children }) => <div className="bss-phones">{children}</div>;
