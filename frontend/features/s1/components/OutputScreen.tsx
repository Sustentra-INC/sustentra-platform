"use client";

/**
 * Output (screen 7) — stub. The spec says product is still researching what the
 * output should be, so this is a reachable route with an honest placeholder and
 * NO invented output format.
 */
export function OutputScreen() {
  return (
    <section className="s1-content s1-output">
      <header className="s1-ws-header">
        <div className="s1-ws-header__id">
          <h1>Output</h1>
          <span className="s1-muted">What the product will produce, so the value is tangible.</span>
        </div>
      </header>

      <div className="s1-output-card">
        <span className="s1-state s1-state--open">Not built</span>
        <h2>The output format is still being decided.</h2>
        <p>
          Product is researching what a verifier and their client should get at the end — an opinion, a workpaper export,
          a data file, or some combination. Nothing is built here yet, and no format is assumed.
        </p>
        <p className="s1-muted">Owner: Claire and Vivian. This screen will fill in once the format is chosen.</p>
      </div>
    </section>
  );
}
