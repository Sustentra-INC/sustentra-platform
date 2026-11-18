/** "1 record", "2 records": a count with its noun in the right number. Adds "s" unless given a plural. */
export function count(n: number, noun: string, plural = `${noun}s`): string {
  return `${n} ${n === 1 ? noun : plural}`;
}
