// Prepared before every test file: extra assertions (toBeInTheDocument…),
// translations, and two browser features jsdom lacks but Mantine uses.
import "@testing-library/jest-dom/vitest";
import "../i18n";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = ResizeObserverStub;

// Scrolling to the chosen option of a list (Select).
Element.prototype.scrollIntoView = vi.fn();

// Font loading events, followed by the textareas that grow with their text.
if (!("fonts" in document)) {
  Object.defineProperty(document, "fonts", { value: new EventTarget() });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
