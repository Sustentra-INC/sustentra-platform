import type { KeyboardEvent } from "react";

import { nextKeyboardIndex } from "../utils/keyboardNavigation";

interface KeyboardNavigationOptions {
  currentIndex: number;
  itemCount: number;
  onMove: (nextIndex: number) => void;
  onEnter?: () => void;
  onSpace?: () => void;
  onEscape?: () => void;
}

export function useKeyboardNavigation({
  currentIndex,
  itemCount,
  onMove,
  onEnter,
  onSpace,
  onEscape,
}: KeyboardNavigationOptions) {
  return function handleKeyboardNavigation(event: KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      onMove(nextKeyboardIndex(currentIndex, itemCount, "down"));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      onMove(nextKeyboardIndex(currentIndex, itemCount, "up"));
    }
    if (event.key === "Enter" && onEnter) {
      event.preventDefault();
      onEnter();
    }
    if (event.key === " " && onSpace) {
      event.preventDefault();
      onSpace();
    }
    if (event.key === "Escape" && onEscape) {
      event.preventDefault();
      onEscape();
    }
  };
}
