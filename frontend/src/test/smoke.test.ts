import { describe, expect, it } from "vitest";

describe("tooling de tests", () => {
  it("corre con el navegador en UTC", () => {
    expect(new Date(0).getTimezoneOffset()).toBe(0);
    expect(document.body).toBeInTheDocument();
  });
});
