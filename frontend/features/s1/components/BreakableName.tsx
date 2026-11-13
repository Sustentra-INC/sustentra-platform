import { Fragment } from "react";

/** A file name that wraps on its separators (underscore, dash, dot, space), never in the middle of a word. */
export function BreakableName({ name }: { name: string }) {
  const parts = name.split(/(?<=[_\-. ])/);
  return (
    <span title={name}>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? <wbr /> : null}
          {part}
        </Fragment>
      ))}
    </span>
  );
}
