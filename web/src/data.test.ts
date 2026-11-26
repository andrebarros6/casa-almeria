import { describe, expect, it } from "vitest";
import { linkError, NotAllowedError, RateLimitedError } from "./data";

describe("linkError", () => {
  it("flags emails without an account", () => {
    expect(linkError({ message: "Signups not allowed for otp", status: 422 })).toBeInstanceOf(
      NotAllowedError,
    );
  });

  it("reads the per-email wait", () => {
    const err = linkError({
      message: "For security purposes, you can only request this after 42 seconds.",
      status: 429,
    });
    expect(err).toBeInstanceOf(RateLimitedError);
    expect((err as RateLimitedError).seconds).toBe(42);
  });

  it("treats the hourly email cap as rate limited without a wait", () => {
    const err = linkError({ message: "email rate limit exceeded", status: 429 });
    expect(err).toBeInstanceOf(RateLimitedError);
    expect((err as RateLimitedError).seconds).toBeNull();
  });

  it("passes other failures through", () => {
    const original = new Error("Failed to fetch");
    expect(linkError(original)).toBe(original);
    const plain = linkError({ message: "boom" });
    expect(plain).not.toBeInstanceOf(RateLimitedError);
    expect(plain.message).toBe("boom");
  });
});
