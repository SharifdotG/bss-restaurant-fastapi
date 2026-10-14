// A file in this repo, linked to GitHub at main so readers can open the real code.
export const Source = ({ path, line, children }) => {
  const href = `https://github.com/SharifdotG/bss-restaurant-fastapi/blob/main/${path}${line ? `#L${line}` : ""}`;
  return (
    <a className="bss-source" href={href} target="_blank" rel="noreferrer">
      <code>{children ?? path}</code>
    </a>
  );
};
