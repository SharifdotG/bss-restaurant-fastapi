// One image with a caption, for captures that have no dark version, like the receipt.
export const Figure = ({ src, alt, caption, narrow }) => (
  <figure className={narrow ? "bss-figure bss-figure-phone" : "bss-figure"}>
    <img className="bss-screen" src={src} alt={alt} />
    {caption && <figcaption>{caption}</figcaption>}
  </figure>
);
