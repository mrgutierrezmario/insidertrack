import { describe, it, expect } from "vitest";
import { C, card, input, buttonPrimary, LABEL_COLORS, OUTCOME_COLORS } from "./theme";

describe("theme constants", () => {
  it("C exposes the semantic palette", () => {
    expect(C.surface).toBeDefined();
    expect(C.text).toBeDefined();
    expect(C.accent).toBeDefined();
    expect(C.success).toBeDefined();
    expect(C.danger).toBeDefined();
  });

  it("every color is a valid 7-char hex string", () => {
    for (const [name, value] of Object.entries(C)) {
      expect(value, `C.${name}`).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it("shared style objects pull from the same palette", () => {
    expect(card.background).toBe(C.surface);
    expect(input.background).toBe(C.bg);
    expect(buttonPrimary.background).toBe(C.accentSolid);
  });

  it("LABEL_COLORS covers all 5 composite labels", () => {
    const expected = ["Strong Watch", "Watch", "Neutral", "High Risk", "Avoid for Now"];
    for (const label of expected) {
      expect(LABEL_COLORS[label]).toBeDefined();
    }
  });

  it("OUTCOME_COLORS covers UP/DOWN/FLAT", () => {
    expect(OUTCOME_COLORS.UP).toBe(C.success);
    expect(OUTCOME_COLORS.DOWN).toBe(C.danger);
    expect(OUTCOME_COLORS.FLAT).toBe(C.textSoft);
  });
});
