"use client";

import { useEffect, useState } from "react";

import { zipFromAddress } from "../api/recalculation";

/**
 * Under a Setup facility: the eGRID subregion(s) EPA lists for the ZIP code in its
 * address (Power Profiler, eGRID2023), with a one-click "Use" when the facility's grid
 * region is not set to it. A ZIP code served by several subregions is chosen by the
 * facility's electric utility (EPA's guidance), so each is offered and none is picked.
 */
export function ZipRegionHint({
  address,
  region,
  lookup,
  onUse,
}: {
  address: string | null | undefined;
  region: string | undefined;
  lookup: (zip: string) => Promise<string[]>;
  onUse: (subregion: string) => void;
}) {
  const zip = zipFromAddress(address);
  const [found, setFound] = useState<{ zip: string; subregions: string[] } | null>(null);

  useEffect(() => {
    if (!zip) return;
    let live = true;
    const timer = window.setTimeout(() => {
      void lookup(zip).then((subregions) => {
        if (live) setFound({ zip, subregions });
      });
    }, 400); // typing an address: look up once it settles
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [zip, lookup]);

  const current = found && found.zip === zip ? found.subregions : [];
  if (!zip || current.length === 0) return null;
  const source = "EPA Power Profiler, eGRID2023";
  if (current.length === 1) {
    const [only] = current;
    return (
      <p className="s1-fac__hint s1-muted">
        ZIP {zip} is in {only} ({source}).
        {region === only ? null : (
          <>
            {region ? ` The grid region is set to ${region}. ` : " "}
            <button className="s1-linklike" type="button" onClick={() => onUse(only)}>
              Use {only}
            </button>
          </>
        )}
      </p>
    );
  }
  return (
    <p className="s1-fac__hint s1-muted">
      ZIP {zip} is served by {current.join(" or ")} ({source}): choose by the facility&rsquo;s electric utility.
      {region && current.includes(region)
        ? null
        : current.map((code) => (
            <span key={code}>
              {" "}
              <button className="s1-linklike" type="button" onClick={() => onUse(code)}>
                Use {code}
              </button>
            </span>
          ))}
    </p>
  );
}
