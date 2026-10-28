/**
 * The request screens take callbacks that answer at once (the fixture store) or after the
 * server has answered (the backend store). These helpers let one component code handle both:
 * with a plain value everything runs synchronously, exactly as it did before the server
 * existed, so the demo's toasts and dialog closes keep their timing.
 */

export type MaybePromise<T> = T | Promise<T>;

/** The title of the banner that says a change did not go through. */
export const NOT_SAVED_TITLE = "That change wasn't saved";

const NOT_SAVED_TEXT = "That change wasn't saved. Try again.";

function isPromise<T>(value: MaybePromise<T>): value is Promise<T> {
  return typeof (value as { then?: unknown } | null | undefined)?.then === "function";
}

/** onDone runs synchronously when the value is not a promise (fixture mode), after it resolves otherwise.
 *  A synchronous throw or a rejection goes to onError. */
export function settle<T>(run: () => MaybePromise<T>, onDone: (value: T) => void, onError: (error: unknown) => void): void {
  let result: MaybePromise<T>;
  try {
    result = run();
  } catch (error) {
    onError(error);
    return;
  }
  if (isPromise(result)) result.then(onDone, onError);
  else onDone(result);
}

/** Maps the value, staying synchronous when it already is; a rejection propagates. */
export function andThen<T, U>(value: MaybePromise<T>, fn: (value: T) => U): MaybePromise<U> {
  return isPromise(value) ? value.then(fn) : fn(value);
}

/** What to tell the person: the error's own sentence when it has one. */
export function problemText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : NOT_SAVED_TEXT;
}
