export interface DemoRequest {
  /** Named groups from the route's pattern, URI-decoded. */
  params: Record<string, string>;
  query: URLSearchParams;
  /** The JSON body as the caller passed it to `api()`. */
  body: unknown;
}

export interface DemoRoute {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** Matched against the path without its query, e.g. /^\/engagements\/(?<id>[^/]+)\/recalculation$/ */
  path: RegExp;
  handle: (request: DemoRequest) => unknown | Promise<unknown>;
}
