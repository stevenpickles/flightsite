import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "@/lib/api/client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("returns the parsed JSON body on a 2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ hello: "world" })),
    );
    await expect(
      apiFetch<{ hello: string }>("/api/internal/config"),
    ).resolves.toEqual({
      hello: "world",
    });
  });

  it("passes the path and init through to fetch unchanged", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    const init: RequestInit = { method: "PUT", body: "{}" };
    await apiFetch("/api/internal/config", init);
    expect(fetchMock).toHaveBeenCalledWith("/api/internal/config", init);
  });

  it("throws an ApiError with a string detail on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ detail: "invalid receiver host" }, 422),
        ),
    );
    await expect(apiFetch("/api/internal/config")).rejects.toMatchObject({
      message: "invalid receiver host",
      status: 422,
    });
  });

  it("joins a validation-error list detail into a single message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: [
              {
                loc: ["body", "port"],
                msg: "port must be >= 1",
                type: "value_error",
              },
              {
                loc: ["body", "host"],
                msg: "host must not be blank",
                type: "value_error",
              },
            ],
          },
          422,
        ),
      ),
    );
    let error: unknown;
    try {
      await apiFetch("/api/internal/config");
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe(
      "port must be >= 1; host must not be blank",
    );
  });

  it("falls back to a generic message when the error body has no usable detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 500 })),
    );
    await expect(apiFetch("/api/internal/config")).rejects.toMatchObject({
      message: "Request failed with status 500",
      status: 500,
    });
  });

  it("parses an empty response body as undefined", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 200 })),
    );
    await expect(
      apiFetch("/api/internal/decoder/test"),
    ).resolves.toBeUndefined();
  });
});
