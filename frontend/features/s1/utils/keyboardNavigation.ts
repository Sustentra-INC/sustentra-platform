export function nextKeyboardIndex(
  currentIndex: number,
  itemCount: number,
  direction: "up" | "down"
): number {
  if (itemCount <= 0) return -1;
  if (direction === "down") {
    return Math.min(currentIndex + 1, itemCount - 1);
  }
  return Math.max(currentIndex - 1, 0);
}
