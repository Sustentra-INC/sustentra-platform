/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { useCallback, useState } from "react";

import { ApiError } from "../../../lib/api";
import { RequestActionError } from "../api/requests";
import { EvidenceRequests } from "../components/EvidenceRequests";
import { engagementConfig } from "../fixtures/engagementConfig";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { coverageRules } from "../fixtures/verification/coverageRules";
import { REQUEST_TIMEOUT_MS, useBackendRequestsStore } from "../requests/backendRequestsStore";
import type { AskDraft } from "../requests/requestsStore";
import type { Ask } from "../types/requests";
import type { Finding } from "../types/verification";
import { useWorkpaperSync } from "../verification/useWorkpaperSync";

/**
 * Requests in backend mode change only through the server's request actions, and the screens show
 * what the server answers. Here the server is a stubbed fetch.
 */

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

/** The server's ask, as the request actions answer with it. */
function serverAsk(over: Partial<Ask> = {}): Ask {
  return {
    id: "ASK-1",
    type: "missing_document",
    whatIsNeeded: "Send the January bill.",
    source: {
      origin: "workspace_document",
      documentId: "DOC-1",
      fieldKey: null,
      itemLabel: "kent_jan.pdf",
      facilityName: "Kent Cannery",
      period: "Jan 2025",
      sourcePage: null,
      arrival: null,
    },
    raisedByName: "member@acme.test",
    raisedByLogin: "member@acme.test",
    raisedAt: "2025-10-28T10:04:00Z",
    state: "not_yet_sent",
    requestNumber: null,
    lineNumber: null,
    linkedFromAskId: null,
    resolution: null,
    withdrawReason: null,
    history: [{ kind: "raised", actorName: "member@acme.test", actorLogin: "member@acme.test", at: "2025-10-28T10:04:00Z" }],
    ...over,
  };
}

const sentVersion = (ask: Ask, requestNumber: number, lineNumber: number): Ask => ({
  ...ask,
  state: "requested",
  requestNumber,
  lineNumber,
  history: [
    ...ask.history,
    { kind: "sent", actorName: "member@acme.test", actorLogin: "member@acme.test", at: "2025-10-28T11:00:00Z", detail: `request ${requestNumber}` },
  ],
});

const draft: AskDraft = {
  origin: "workspace_document",
  documentId: "DOC-1",
  itemLabel: "kent_jan.pdf",
  facilityName: "Kent Cannery",
  period: "Jan 2025",
  type: "missing_document",
  whatIsNeeded: "Send the January bill.",
  raisedByName: "M. Osei",
  raisedByLogin: "mosei",
};

const NOT_SAVED = "The change wasn't saved. Check your connection and try again.";
const SESSION_ENDED = "Your session ended. Sign in again to continue.";

type Options = { engagementId: string; onSessionEnded?: (error: unknown) => boolean };

function renderStore(options: Options = { engagementId: "ENG-1" }) {
  return renderHook((props: Options) => useBackendRequestsStore(props), { initialProps: options });
}

const lastCall = () => {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init };
};

/** A fetch that never answers, and gives up when its signal aborts, as a real one does. */
function hang() {
  fetchMock.mockImplementation(
    (_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
      })
  );
}

describe("saveAsk", () => {
  it("posts what a person writes, and holds the ask the server made, raised by the signed-in user", async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      json(serverAsk({ id: JSON.parse(String(init.body)).id }), 201)
    );
    const { result } = renderStore();

    let saved!: Ask;
    await act(async () => {
      saved = await result.current.saveAsk(draft);
    });

    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/engagements/ENG-1/requests");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.id).toMatch(/^ASK-[a-z0-9]+-[a-z0-9]{1,8}$/);
    expect(body).not.toHaveProperty("raisedByName");
    expect(body).not.toHaveProperty("raisedByLogin");
    expect(String(init.body)).not.toContain("M. Osei");

    expect(saved).toEqual(serverAsk({ id: body.id }));
    expect(saved.raisedByName).toBe("member@acme.test");
    expect(result.current.asks).toEqual([saved]);
  });

  it("makes a new id each time", async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      json(serverAsk({ id: JSON.parse(String(init.body)).id }), 201)
    );
    const { result } = renderStore();
    await act(async () => {
      await result.current.saveAsk(draft);
      await result.current.saveAsk(draft);
    });
    const ids = fetchMock.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)).id);
    expect(new Set(ids).size).toBe(2);
    expect(result.current.asks).toHaveLength(2);
  });

  it("adds a new ask at the end and replaces a known one where it stands", async () => {
    const first = serverAsk({ id: "ASK-1" });
    const second = serverAsk({ id: "ASK-2" });
    const { result } = renderStore();
    act(() => result.current.replaceAsks([first, second]));

    // The server answers a create with an id the store already holds: it takes that place.
    const again = serverAsk({ id: "ASK-1", whatIsNeeded: "Changed on the server." });
    fetchMock.mockImplementation(() => json(again, 201));
    await act(async () => {
      await result.current.saveAsk(draft);
    });
    expect(result.current.asks).toEqual([again, second]);

    const third = serverAsk({ id: "ASK-3" });
    fetchMock.mockImplementation(() => json(third, 201));
    await act(async () => {
      await result.current.saveAsk(draft);
    });
    expect(result.current.asks).toEqual([again, second, third]);
  });
});

describe("sendAsks", () => {
  it("replaces both asks with the server's and resolves to the request they became", async () => {
    const one = serverAsk({ id: "ASK-1" });
    const two = serverAsk({ id: "ASK-2" });
    const bystander = serverAsk({ id: "ASK-9" });
    const sentOne = sentVersion(one, 4, 1);
    const sentTwo = sentVersion(two, 4, 1);
    fetchMock.mockImplementation(() =>
      json({ requestNumber: 4, sentAt: "2025-10-28T11:00:00Z", askIds: ["ASK-1", "ASK-2"], asks: [sentOne, sentTwo] })
    );
    const { result } = renderStore();
    act(() => result.current.replaceAsks([one, bystander, two]));

    let sent: unknown;
    await act(async () => {
      sent = await result.current.sendAsks(["ASK-1", "ASK-2"], { "ASK-1": 1, "ASK-2": 1 });
    });

    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/engagements/ENG-1/requests/send");
    expect(JSON.parse(String(init.body))).toEqual({ askIds: ["ASK-1", "ASK-2"], lineNumbers: { "ASK-1": 1, "ASK-2": 1 } });
    expect(sent).toEqual({ requestNumber: 4, sentAt: "2025-10-28T11:00:00Z", askIds: ["ASK-1", "ASK-2"] });
    expect(result.current.asks).toEqual([sentOne, bystander, sentTwo]);
    expect(result.current.requests.map((r) => r.requestNumber)).toEqual([4]);
    expect(result.current.requests[0].askIds).toEqual(["ASK-1", "ASK-2"]);
  });
});

describe("editAsk", () => {
  it("sends the trimmed text and holds the ask the server answers with", async () => {
    const edited = serverAsk({ whatIsNeeded: "New words." });
    fetchMock.mockImplementation(() => json(edited));
    const { result } = renderStore();
    act(() => result.current.replaceAsks([serverAsk()]));

    await act(async () => {
      await result.current.editAsk("ASK-1", "  New words.  ");
    });

    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/engagements/ENG-1/requests/ASK-1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ whatIsNeeded: "New words." });
    expect(result.current.asks).toEqual([edited]);
  });

  it("refuses text that is blank after trimming, with no call to the server", async () => {
    const { result } = renderStore();
    await act(async () => {
      await expect(result.current.editAsk("ASK-1", "   ")).rejects.toMatchObject({
        message: "Write what is needed. The request keeps its earlier text.",
        status: null,
      });
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses more than 2,000 characters, with no call, and sends exactly 2,000 once trimmed", async () => {
    const { result } = renderStore();
    await act(async () => {
      const refused = result.current.editAsk("ASK-1", "x".repeat(2001));
      await expect(refused).rejects.toBeInstanceOf(RequestActionError);
      await expect(refused).rejects.toThrow("Keep what is needed under 2,000 characters.");
    });
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockImplementation(() => json(serverAsk()));
    await act(async () => {
      await result.current.editAsk("ASK-1", `  ${"x".repeat(2000)}  `);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(lastCall().init.body)).whatIsNeeded).toHaveLength(2000);
  });
});

describe("resolveAsk and withdrawAsk", () => {
  it("resolves with the link and note, and holds the server's ask", async () => {
    const held = sentVersion(serverAsk(), 3, 1);
    const resolved = {
      ...held,
      state: "resolved" as const,
      resolution: { at: "2025-10-28T12:00:00Z", by: "member@acme.test", link: "https://x.test/f", note: "Sent by email." },
    };
    fetchMock.mockImplementation(() => json(resolved));
    const { result } = renderStore();
    act(() => result.current.replaceAsks([held]));

    await act(async () => {
      await result.current.resolveAsk("ASK-1", { link: "https://x.test/f", note: "Sent by email." });
    });

    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/requests/ASK-1/resolve");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ link: "https://x.test/f", note: "Sent by email." });
    expect(result.current.asks).toEqual([resolved]);
  });

  it("shows the server's sentence on a 409, then the requests as the server holds them", async () => {
    const sentence = "Request 3 hasn't been sent yet, so it can't be resolved. Send it first, or withdraw it.";
    const stale = sentVersion(serverAsk({ id: "ASK-1" }), 3, 1);
    const truth = serverAsk({ id: "ASK-1" });
    const other = serverAsk({ id: "ASK-2", whatIsNeeded: "Added elsewhere." });
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      init.method === "POST"
        ? json({ detail: sentence }, 409)
        : json({
            items: [truth, other].map((payload) => ({ kind: "ask", item_key: payload.id, payload, created_at: "", updated_at: "" })),
          })
    );
    const { result } = renderStore();
    act(() => result.current.replaceAsks([stale]));

    await act(async () => {
      const failed = result.current.resolveAsk("ASK-1");
      await expect(failed).rejects.toBeInstanceOf(RequestActionError);
      await expect(failed).rejects.toMatchObject({ message: sentence, status: 409 });
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/workpaper-items?kind=ask");
    expect(result.current.asks).toEqual([truth, other]);
  });

  it("reloads on a 404 too, and leaves the asks alone if the reload fails", async () => {
    const held = serverAsk();
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      init.method === "POST" ? json({ detail: "Request not found." }, 404) : json({ detail: "Nope." }, 500)
    );
    const { result } = renderStore();
    act(() => result.current.replaceAsks([held]));

    await act(async () => {
      await expect(result.current.withdrawAsk("ASK-1", "No longer needed.")).rejects.toMatchObject({
        message: "This request is no longer in this engagement. The list now shows the current requests.",
        status: 404,
      });
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.asks).toEqual([held]);
  });

  it("does not reload after a failure that is not a 404 or a 409", async () => {
    fetchMock.mockImplementation(() => json({ detail: "Boom." }, 500));
    const { result } = renderStore();
    await act(async () => {
      await expect(result.current.resolveAsk("ASK-1")).rejects.toMatchObject({
        message: "Something went wrong on our side, so the request wasn't resolved. Try again; if it happens again, tell us.",
        status: 500,
      });
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the names an old request holds, and shows exactly what the server answers", async () => {
    const legacy = sentVersion(
      serverAsk({
        raisedByName: "M. Osei",
        raisedByLogin: "mosei",
        history: [{ kind: "raised", actorName: "M. Osei", actorLogin: "mosei", at: "2025-09-14T16:20:00Z" }],
      }),
      1,
      1
    );
    const withdrawn: Ask = {
      ...legacy,
      state: "withdrawn",
      withdrawReason: "No longer needed.",
      history: [
        ...legacy.history,
        { kind: "withdrawn", actorName: "member@acme.test", actorLogin: "member@acme.test", at: "2025-10-28T12:00:00Z", detail: "No longer needed." },
      ],
    };
    fetchMock.mockImplementation(() => json(withdrawn));
    const { result } = renderStore();
    act(() => result.current.replaceAsks([legacy]));

    await act(async () => {
      await result.current.withdrawAsk("ASK-1", "No longer needed.");
    });

    expect(JSON.parse(String(lastCall().init.body))).toEqual({ reason: "No longer needed." });
    expect(result.current.asks).toEqual([withdrawn]);
    expect(result.current.asks[0].raisedByName).toBe("M. Osei");
    expect(result.current.asks[0].history[0].actorName).toBe("M. Osei");
  });
});

describe("no engagement", () => {
  it("refuses every action before any call", async () => {
    const { result } = renderStore({ engagementId: "" });
    const sentence = "Create or pick an engagement in Setup before raising requests.";
    await act(async () => {
      for (const attempt of [
        () => result.current.saveAsk(draft),
        () => result.current.editAsk("ASK-1", "Text."),
        () => result.current.sendAsks(["ASK-1"]),
        () => result.current.resolveAsk("ASK-1"),
        () => result.current.withdrawAsk("ASK-1", "Reason."),
      ]) {
        await expect(attempt()).rejects.toMatchObject({ message: sentence, status: null });
      }
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("a session that ended", () => {
  it("tells the page once, and says to sign in again", async () => {
    fetchMock.mockImplementation(() => json({ detail: "Not authenticated" }, 401));
    const onSessionEnded = vi.fn(() => true);
    const { result } = renderStore({ engagementId: "ENG-1", onSessionEnded });

    await act(async () => {
      await expect(result.current.sendAsks(["ASK-1"])).rejects.toMatchObject({ message: SESSION_ENDED, status: 401 });
    });

    expect(onSessionEnded).toHaveBeenCalledTimes(1);
    expect(onSessionEnded).toHaveBeenCalledWith(expect.any(ApiError));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("says to sign in again whenever the page says the error ended the session", async () => {
    fetchMock.mockImplementation(() => json({ detail: "Forbidden" }, 403));
    const { result } = renderStore({ engagementId: "ENG-1", onSessionEnded: () => true });
    await act(async () => {
      await expect(result.current.resolveAsk("ASK-1")).rejects.toMatchObject({ message: SESSION_ENDED, status: 403 });
    });
  });

  it("uses the latest handler the page gave", async () => {
    fetchMock.mockImplementation(() => json({ detail: "Not authenticated" }, 401));
    const first = vi.fn(() => false);
    const second = vi.fn(() => true);
    const { result, rerender } = renderStore({ engagementId: "ENG-1", onSessionEnded: first });
    rerender({ engagementId: "ENG-1", onSessionEnded: second });
    await act(async () => {
      await expect(result.current.resolveAsk("ASK-1")).rejects.toMatchObject({ message: SESSION_ENDED });
    });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});

describe("the engagement changes while a call is on its way", () => {
  it("does not add the late answer to the new engagement's requests", async () => {
    const late = deferred<Response>();
    fetchMock.mockImplementation(() => late.promise);
    const { result, rerender } = renderStore({ engagementId: "ENG-1" });
    const theirs = serverAsk({ id: "ASK-OTHER", whatIsNeeded: "Belongs to engagement 2." });

    let saving!: Promise<Ask>;
    act(() => {
      saving = result.current.saveAsk(draft);
    });
    rerender({ engagementId: "ENG-2" });
    act(() => result.current.replaceAsks([theirs]));

    const created = serverAsk({ id: "ASK-LATE" });
    await act(async () => {
      late.resolve(new Response(JSON.stringify(created), { status: 201 }));
      // The ask was made, so the caller still gets it.
      await expect(saving).resolves.toEqual(created);
    });

    expect(lastCall().url).toBe("/api/v1/engagements/ENG-1/requests");
    expect(result.current.asks).toEqual([theirs]);
  });

  it("does not show the old engagement's requests after a late 409", async () => {
    const late = deferred<Response>();
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      init.method === "POST" ? late.promise : json({ items: [] })
    );
    const { result, rerender } = renderStore({ engagementId: "ENG-1" });
    const theirs = serverAsk({ id: "ASK-OTHER" });

    let resolving!: Promise<void>;
    act(() => {
      resolving = result.current.resolveAsk("ASK-1");
    });
    rerender({ engagementId: "ENG-2" });
    act(() => result.current.replaceAsks([theirs]));

    await act(async () => {
      late.resolve(new Response(JSON.stringify({ detail: "Request 1 hasn't been sent yet." }), { status: 409 }));
      await expect(resolving).rejects.toMatchObject({ status: 409 });
    });

    expect(result.current.asks).toEqual([theirs]);
  });

  it("acts on the engagement open when it was called", async () => {
    fetchMock.mockImplementation(() => json(serverAsk()));
    const { result, rerender } = renderStore({ engagementId: "ENG-1" });
    rerender({ engagementId: "ENG-2" });
    await act(async () => {
      await result.current.editAsk("ASK-1", "Text.");
    });
    expect(lastCall().url).toBe("/api/v1/engagements/ENG-2/requests/ASK-1");
  });
});

describe("a call that never answers", () => {
  it("gives up after the limit, and says the change wasn't saved", async () => {
    vi.useFakeTimers();
    hang();
    const { result } = renderStore();

    const settled = vi.fn();
    const failed = result.current.sendAsks(["ASK-1"]).catch((error: unknown) => {
      settled();
      return error;
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1);
    });
    expect(settled).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const error = await failed;
    expect(settled).toHaveBeenCalledTimes(1);
    expect(error).toBeInstanceOf(RequestActionError);
    expect(error).toMatchObject({ message: NOT_SAVED, status: null });
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
    expect(result.current.asks).toEqual([]);
  });

  it("bounds every action, and the reload that follows a 409", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation((_url: string, init: RequestInit) =>
      init.method === "POST"
        ? json({ detail: "Request 3 was already sent." }, 409)
        : new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          })
    );
    const { result } = renderStore();
    const failed = result.current.withdrawAsk("ASK-1", "Reason.").catch((error: unknown) => error);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    });
    // The sentence is the server's; the hung reload did not hold it back for good.
    await expect(failed).resolves.toMatchObject({ message: "Request 3 was already sent.", status: 409 });
    expect((fetchMock.mock.calls[1][1] as RequestInit).signal?.aborted).toBe(true);

    for (const attempt of [
      () => result.current.saveAsk(draft),
      () => result.current.editAsk("ASK-1", "Text."),
      () => result.current.resolveAsk("ASK-1"),
    ]) {
      hang();
      const timedOut = attempt().catch((error: unknown) => error);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
      });
      await expect(timedOut).resolves.toMatchObject({ message: NOT_SAVED, status: null });
    }
  });

  it("re-enables Mark as sent, and says why, once the limit has passed", async () => {
    vi.useFakeTimers();
    hang();
    const { result } = renderStore();
    render(
      <EvidenceRequests
        engagement={engagementConfig}
        asks={seedAsks}
        coverage={{ rules: coverageRules }}
        valuesToReview={0}
        onReview={vi.fn()}
        onOpenSource={vi.fn()}
        onSaveAsk={vi.fn()}
        onSend={(ids, lines) => result.current.sendAsks(ids, lines).then((sent) => sent.requestNumber)}
        onResolve={vi.fn()}
        onWithdraw={vi.fn()}
        onEdit={vi.fn()}
        onRaiseFollowUp={vi.fn()}
        serverRecordsActor
      />
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select kent_gas_sep_2025.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: /^Send \(1\)/ }));
    const panel = screen.getByRole("dialog", { name: "Send requests" });
    const markSent = within(panel).getByRole("button", { name: "Mark as sent" });
    fireEvent.click(markSent);
    expect(markSent).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1);
    });
    expect(markSent).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(markSent).toBeEnabled();
    expect(within(panel).getByRole("alert")).toHaveTextContent(NOT_SAVED);
    expect(screen.getByRole("dialog", { name: "Send requests" })).toBe(panel);
  });
});

describe("requests and the workpaper sync", () => {
  const NOOP = () => undefined;
  const finding: Finding = {
    id: "F-1",
    dataPointId: "vr:s1-mobile",
    dataPointLabel: "Scope 1 · Mobile combustion",
    sentence: "Fleet emissions are left out.",
    cause: "Incomplete inputs",
    magnitude: "",
    status: "Open",
    withClientSince: null,
  };

  it("saves a changed finding but never puts a request, even after a request action", async () => {
    const held = serverAsk({ id: "ASK-1" });
    const withdrawn: Ask = { ...held, state: "withdrawn", withdrawReason: "No longer needed." };
    const item = (kind: string, key: string, payload: object) => ({ kind, item_key: key, payload, created_at: "", updated_at: "" });
    fetchMock.mockImplementation((url: string, init: RequestInit = {}) => {
      if (init.method === "PUT") return json(item("finding", "F-1", {}));
      if (init.method === "POST") return json(withdrawn);
      if (url.endsWith("/workpaper-items")) return json({ items: [item("ask", "ASK-1", held), item("finding", "F-1", finding)] });
      return json({ detail: "Unexpected." }, 500);
    });

    const { result } = renderHook(() => {
      const requests = useBackendRequestsStore({ engagementId: "ENG-1" });
      const [findings, setFindings] = useState<Finding[]>([]);
      const replaceVerification = useCallback((_examinations: unknown, loaded: Finding[]) => setFindings(loaded), []);
      const sync = useWorkpaperSync({
        enabled: true,
        engagementId: "ENG-1",
        findings,
        examinations: {},
        documents: {},
        replaceAsks: requests.replaceAsks,
        replaceVerification,
        replaceDocuments: NOOP,
        onError: NOOP,
      });
      return { requests, sync, findings, setFindings };
    });

    // The engagement's requests come from the same load as its findings.
    await waitFor(() => expect(result.current.sync.loaded).toBe(true));
    expect(result.current.requests.asks).toEqual([held]);
    expect(result.current.findings).toEqual([finding]);

    // A request action changes the asks held here ...
    await act(async () => {
      await result.current.requests.withdrawAsk("ASK-1", "No longer needed.");
    });
    expect(result.current.requests.asks).toEqual([withdrawn]);

    // ... and a change to a finding is still saved.
    act(() => result.current.setFindings([{ ...finding, status: "Closed" }]));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/engagements/ENG-1/workpaper-items/finding/F-1",
        expect.objectContaining({ method: "PUT" })
      )
    );

    const puts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT").map(([url]) => url);
    expect(puts).toEqual(["/api/v1/engagements/ENG-1/workpaper-items/finding/F-1"]);
    expect(puts.some((url) => String(url).includes("/workpaper-items/ask/"))).toBe(false);
  });
});
