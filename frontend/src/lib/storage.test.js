import { describe, it, expect } from "vitest";
import { EMAIL_KEY, ADMIN_TOKEN_KEY, ADMIN_SESSION_KEY } from "./storage";

describe("storage keys", () => {
  it("exports stable, prefixed string constants", () => {
    expect(EMAIL_KEY).toBe("insidertrack_email");
    expect(ADMIN_TOKEN_KEY).toBe("insidertrack_admin_token");
    expect(ADMIN_SESSION_KEY).toBe("insidertrack_admin_v1");
  });

  it("keys are distinct (no accidental collisions)", () => {
    const keys = [EMAIL_KEY, ADMIN_TOKEN_KEY, ADMIN_SESSION_KEY];
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("all keys share the insidertrack_ namespace", () => {
    for (const k of [EMAIL_KEY, ADMIN_TOKEN_KEY, ADMIN_SESSION_KEY]) {
      expect(k.startsWith("insidertrack_")).toBe(true);
    }
  });
});
