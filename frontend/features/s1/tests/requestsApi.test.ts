/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api";
import {
  RequestActionError,
  createRequest,
  editRequest,
  loadAsks,
  requestActionMessage,
  requestBodyFromDraft,
  resolveRequest,
  sendRequests,
  withdrawRequest,
} from "../api/requests";
import type { RequestAction } from "../api/requests";
import type { AskDraft } from "../requests/requestsStore";
import { findBlockedUiTerms } from "../utils/copyCompliance";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

const draft: AskDraft = {
  origin: "review_value",
  documentId: "DOC-1",
  fieldKey: "candidate:x",
  itemLabel: "Kent electricity Jan",
  facilityName: null,
  period: "2024-01",
  sourcePage: 2,
  type: "clarify",
  whatIsNeeded: "Resend p.2",
  raisedByName: "M. Osei",
  raisedByLogin: "mosei",
};

const lastCall = () => {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return { url: url as string, init: init as RequestInit };
};

describe("request actions client", () => {
  it("creates a request with the draft's own fields only", async () => {
    const created = { id: "ASK-1", state: "not_yet_sent", raisedByName: "M. Osei" };
    fetchMock.mockImplementation(() => reply(created, 201));

    const result = await createRequest("ENG-1", requestBodyFromDraft("ASK-1", draft));

    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/engagements/ENG-1/requests");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      '{"id":"ASK-1","type":"clarify","whatIsNeeded":"Resend p.2","source":{"origin":"review_value",' +
        '"documentId":"DOC-1","fieldKey":"candidate:x","itemLabel":"Kent electricity Jan","facilityName":null,' +
        '"period":"2024-01","sourcePage":2,"arrival":null},"linkedFromAskId":null}'
    );
    expect(init.body).not.toContain("M. Osei");
    expect(init.body).not.toContain("raisedBy");
    expect(result).toEqual(created);
  });

  it("clamps the draft to the server's limits", () => {
    const long = requestBodyFromDraft("ASK-1", { ...draft, itemLabel: `  ${"x".repeat(350)}  ` });
    expect(long.source.itemLabel).toHaveLength(300);
    expect(long.source.itemLabel).toBe(`${"x".repeat(299)}…`);

    expect(requestBodyFromDraft("ASK-1", { ...draft, itemLabel: "   " }).source.itemLabel).toBe("Unnamed item");
    expect(requestBodyFromDraft("ASK-1", { ...draft, itemLabel: "  Kent  " }).source.itemLabel).toBe("Kent");

    expect(requestBodyFromDraft("ASK-1", { ...draft, facilityName: "  " }).source.facilityName).toBeNull();
    expect(requestBodyFromDraft("ASK-1", { ...draft, facilityName: " Kent site " }).source.facilityName).toBe("Kent site");
    const cut = requestBodyFromDraft("ASK-1", {
      ...draft,
      facilityName: "f".repeat(400),
      period: "p".repeat(400),
      arrival: ` ${"a".repeat(400)}`,
    }).source;
    expect([cut.facilityName, cut.period, cut.arrival].map((v) => v?.length)).toEqual([300, 300, 300]);

    expect(requestBodyFromDraft("ASK-1", { ...draft, sourcePage: 0 }).source.sourcePage).toBeNull();
    expect(requestBodyFromDraft("ASK-1", { ...draft, sourcePage: 2.7 }).source.sourcePage).toBe(2);
    expect(requestBodyFromDraft("ASK-1", { ...draft, sourcePage: null }).source.sourcePage).toBeNull();
    expect(requestBodyFromDraft("ASK-1", { ...draft, sourcePage: Number.NaN }).source.sourcePage).toBeNull();

    expect(requestBodyFromDraft("ASK-1", { ...draft, whatIsNeeded: "  Resend p.2 \n" }).whatIsNeeded).toBe("Resend p.2");
  });

  it("drops a document or field reference that is absent or too long", () => {
    const body = (patch: Partial<AskDraft>) => requestBodyFromDraft("ASK-1", { ...draft, ...patch }).source;
    expect(body({ documentId: undefined, fieldKey: undefined })).toMatchObject({ documentId: null, fieldKey: null });
    expect(body({ documentId: "d".repeat(501), fieldKey: "f".repeat(501) })).toMatchObject({
      documentId: null,
      fieldKey: null,
    });
    expect(body({ documentId: "d".repeat(500) }).documentId).toHaveLength(500);
  });

  it("starts a draft with no origin as a workspace document, and keeps a follow-up link", () => {
    const body = requestBodyFromDraft("ASK-2", { ...draft, origin: undefined, linkedFromAskId: "ASK-1" });
    expect(body.source.origin).toBe("workspace_document");
    expect(body.linkedFromAskId).toBe("ASK-1");
  });

  it("counts characters as the server does, so a cut never splits a symbol", () => {
    const label = `${"x".repeat(298)}${"😀".repeat(5)}`; // 303 characters, 308 UTF-16 units
    const cut = requestBodyFromDraft("ASK-1", { ...draft, itemLabel: label }).source.itemLabel;
    expect(cut).toBe(`${"x".repeat(298)}😀…`);
    expect(Array.from(cut)).toHaveLength(300);
    expect(JSON.parse(JSON.stringify(cut))).toBe(cut);
  });

  it("edits a request's text with PATCH, keyed by a URL-safe id", async () => {
    fetchMock.mockImplementation(() => reply({ id: "ASK 1/x", whatIsNeeded: "New text" }));
    const result = await editRequest("ENG-1", "ASK 1/x", "New text");
    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/engagements/ENG-1/requests/ASK_1_x");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ whatIsNeeded: "New text" });
    expect(result.whatIsNeeded).toBe("New text");
  });

  it("encodes the engagement id in every path", async () => {
    fetchMock.mockImplementation(() => reply({ items: [] }));
    await loadAsks("ENG/1 x");
    expect(lastCall().url).toBe("/api/v1/engagements/ENG%2F1%20x/workpaper-items?kind=ask");
  });

  it("sends requests together, with line numbers only when there are some", async () => {
    const sent = { requestNumber: 3, sentAt: "2026-10-28T10:04:00Z", askIds: ["A", "B"], asks: [] };
    fetchMock.mockImplementation(() => reply(sent));

    const result = await sendRequests("ENG-1", ["A", "B"], { A: 1, B: 1 });
    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/requests/send");
    expect(lastCall().init.method).toBe("POST");
    expect(lastCall().init.body).toBe('{"askIds":["A","B"],"lineNumbers":{"A":1,"B":1}}');
    expect(result).toEqual(sent);

    await sendRequests("ENG-1", ["A"]);
    expect(lastCall().init.body).toBe('{"askIds":["A"]}');
    await sendRequests("ENG-1", ["A"], {});
    expect(lastCall().init.body).toBe('{"askIds":["A"]}');
  });

  it("resolves a request with the link and note, or with neither", async () => {
    fetchMock.mockImplementation(() => reply({ id: "ASK 1/x", state: "resolved" }));

    await resolveRequest("ENG-1", "ASK 1/x", { note: "Got it" });
    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/requests/ASK_1_x/resolve");
    expect(lastCall().init.method).toBe("POST");
    expect(lastCall().init.body).toBe('{"link":null,"note":"Got it"}');

    await resolveRequest("ENG-1", "A", { link: "https://example.com/doc", note: "" });
    expect(lastCall().init.body).toBe('{"link":"https://example.com/doc","note":null}');

    await resolveRequest("ENG-1", "A");
    expect(lastCall().init.body).toBe('{"link":null,"note":null}');
  });

  it("withdraws a request with a reason", async () => {
    fetchMock.mockImplementation(() => reply({ id: "ASK 1/x", state: "withdrawn" }));
    await withdrawRequest("ENG-1", "ASK 1/x", "Duplicate");
    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/requests/ASK_1_x/withdraw");
    expect(lastCall().init.method).toBe("POST");
    expect(lastCall().init.body).toBe('{"reason":"Duplicate"}');
  });

  it("loads the engagement's requests from their saved payloads", async () => {
    fetchMock.mockImplementation(() =>
      reply({
        items: [
          { kind: "ask", item_key: "ASK-1", payload: { id: "ASK-1", whatIsNeeded: "Resend p.2" } },
          { kind: "ask", item_key: "ASK-2", payload: { id: "ASK-2", whatIsNeeded: "Send the lease" } },
        ],
      })
    );
    const asks = await loadAsks("ENG-1");
    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/workpaper-items?kind=ask");
    expect(lastCall().init.method).toBeUndefined();
    expect(asks.map((a) => a.id)).toEqual(["ASK-1", "ASK-2"]);
  });

  it("lets a failed action reach the caller as the server's ApiError", async () => {
    fetchMock.mockImplementation(() => reply({ detail: "Engagement is archived." }, 409));
    const failure = await createRequest("ENG-1", requestBodyFromDraft("ASK-1", draft)).catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(requestActionMessage(failure, "create")).toBe("This engagement is archived, so its requests can't change.");

    fetchMock.mockImplementation(() =>
      reply({ detail: [{ loc: ["body", "reason"], msg: "String should have at most 1000 characters", type: "string_too_long" }] }, 422)
    );
    const invalid = await withdrawRequest("ENG-1", "A", "x").catch((e: unknown) => e);
    expect(requestActionMessage(invalid, "withdraw")).toBe("Give a reason for withdrawing, in up to 1,000 characters.");

    fetchMock.mockImplementation(() => Promise.resolve(new Response("<html>Bad gateway</html>", { status: 502 })));
    const down = await editRequest("ENG-1", "A", "x").catch((e: unknown) => e);
    expect(requestActionMessage(down, "edit")).toBe(
      "Something went wrong on our side, so the text wasn't saved. Try again; if it happens again, tell us."
    );
  });

  it("carries a message and a status on RequestActionError", () => {
    const error = new RequestActionError("The change wasn't saved.", 409);
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("RequestActionError");
    expect(error.message).toBe("The change wasn't saved.");
    expect(error.status).toBe(409);
    expect(new RequestActionError("Lost.", null).status).toBeNull();
  });
});

const failure = (status: number, detail: unknown, message?: string) =>
  new ApiError(status, message ?? (typeof detail === "string" ? detail : "validation"), { detail }, null);

const validation = (field: string | number, type = "string_too_long") =>
  failure(422, [{ loc: ["body", field], msg: "invalid", type }], `${field}: invalid`);

const SENT_BEFORE =
  "Request 3 was already sent, so its text can't change. Withdraw it and add a new request instead.";
const NO_SUCH_REQUEST =
  "There is no request 'ASK-9' in this engagement, so nothing was sent. Reload the page to see the current requests.";
const NOT_VALID =
  "This change couldn't be saved because some of its details aren't valid. Reload the page and try again.";
const GONE = "This request is no longer in this engagement. The list now shows the current requests.";

describe("requestActionMessage", () => {
  const rows: Array<[string, unknown, RequestAction, string]> = [
    ["409 archived", failure(409, "Engagement is archived."), "create", "This engagement is archived, so its requests can't change."],
    ["409 duplicate id", failure(409, "A request with this id already exists."), "create", "This request was already added. The list now shows it."],
    ["409 the server's sentence", failure(409, SENT_BEFORE), "edit", SENT_BEFORE],
    ["404 request not found", failure(404, "Request not found."), "resolve", GONE],
    ["404 not a sentence", failure(404, "Not Found"), "withdraw", GONE],
    ["404 with no detail", new ApiError(404, "Request failed (404)", null, null), "edit", GONE],
    ["404 a list", failure(404, [{ loc: ["path"], msg: "x", type: "x" }]), "edit", GONE],
    ["404 from the send endpoint", failure(404, NO_SUCH_REQUEST), "send", NO_SUCH_REQUEST],
    ["404 engagement not found", failure(404, "Engagement not found."), "create", "Engagement not found."],
    ["403", failure(403, "Forbidden."), "create", "Your role can view requests but not change them."],
    ["401", failure(401, "Not authenticated."), "send", "Your session ended. Sign in again to continue."],
    ["422 a sentence", failure(422, "Request 3 is not a thing."), "send", "Request 3 is not a thing."],
    [
      "422 history too long",
      failure(422, "This request's history is too long to record another change. Withdraw it and add a new request instead."),
      "resolve",
      "This request's history is too long to record another change. Withdraw it and add a new request instead.",
    ],
    ["422 whatIsNeeded", validation("whatIsNeeded", "string_too_short"), "edit", "Write what is needed, in up to 2,000 characters."],
    ["422 reason", validation("reason"), "withdraw", "Give a reason for withdrawing, in up to 1,000 characters."],
    ["422 link", validation("link"), "resolve", "Keep the link and the note under 2,000 characters each."],
    ["422 note", validation("note"), "resolve", "Keep the link and the note under 2,000 characters each."],
    ["422 itemLabel", validation("itemLabel"), "create", "The item's name is too long to save. Shorten it and try again."],
    ["422 askIds too long", validation("askIds", "too_long"), "send", "Send at most 200 requests at once."],
    ["422 askIds empty", validation("askIds", "too_short"), "send", NOT_VALID],
    ["422 askIds repeated", validation("askIds", "value_error"), "send", NOT_VALID],
    ["422 one askId malformed", validation(3, "string_pattern_mismatch"), "send", NOT_VALID],
    ["422 anything else", validation("sourcePage", "greater_than_equal"), "create", NOT_VALID],
    [
      "422 the first field we can name",
      failure(422, [
        { loc: ["body", "source", "documentId"], msg: "x", type: "string_too_long" },
        { loc: ["body", "whatIsNeeded"], msg: "x", type: "string_too_short" },
      ]),
      "create",
      "Write what is needed, in up to 2,000 characters.",
    ],
    ["422 a list that is not errors", failure(422, ["nonsense", null]), "create", NOT_VALID],
    ["422 with no detail", new ApiError(422, "Request failed (422)", null, null), "create", NOT_VALID],
    ["500 create", failure(500, "Internal Server Error"), "create", "Something went wrong on our side, so the request wasn't added. Try again; if it happens again, tell us."],
    ["500 edit", failure(500, "x"), "edit", "Something went wrong on our side, so the text wasn't saved. Try again; if it happens again, tell us."],
    ["500 send", failure(500, "x"), "send", "Something went wrong on our side, so the requests weren't marked sent. Try again; if it happens again, tell us."],
    ["500 resolve", failure(500, "x"), "resolve", "Something went wrong on our side, so the request wasn't resolved. Try again; if it happens again, tell us."],
    ["500 withdraw", failure(500, "x"), "withdraw", "Something went wrong on our side, so the request wasn't withdrawn. Try again; if it happens again, tell us."],
    ["502", new ApiError(502, "Request failed (502)", null, null), "send", "Something went wrong on our side, so the requests weren't marked sent. Try again; if it happens again, tell us."],
    ["a lost connection", new TypeError("Failed to fetch"), "create", "The change wasn't saved. Check your connection and try again."],
    ["something else", "boom", "edit", "The change wasn't saved. Check your connection and try again."],
    ["409 with no detail", new ApiError(409, "Request failed (409)", null, null), "edit", "The change wasn't saved. Check your connection and try again."],
    ["a status we do not name", failure(429, "Too many requests."), "create", "The change wasn't saved. Check your connection and try again."],
  ];

  it.each(rows)("%s", (_name, error, action, message) => {
    expect(requestActionMessage(error, action)).toBe(message);
  });

  it("uses no term the interface avoids", () => {
    const actions: RequestAction[] = ["create", "edit", "send", "resolve", "withdraw"];
    const messages = [
      ...rows.map(([, error, action]) => requestActionMessage(error, action)),
      ...actions.map((action) => requestActionMessage(failure(500, "x"), action)),
    ];
    expect(messages.length).toBeGreaterThan(rows.length);
    for (const message of messages) {
      expect(findBlockedUiTerms(message), message).toEqual([]);
      expect(message).toMatch(/[.]$/);
    }
  });
});
