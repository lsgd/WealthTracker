/**
 * Whitespace handling for fields where a space at the edge is never meaningful
 * — a search query, a match text, a category name.
 *
 * Leading space goes immediately: nothing can precede the first character, and
 * pasting a name copied out of a statement routinely brings one along.
 * Trailing space survives until the field is left, because while typing it is
 * usually the start of the next word.
 */
export function trimLeading(value: string): string {
  return value.replace(/^\s+/, '');
}

/** Handlers that keep a text input free of edge whitespace as it is used. */
export function trimmedInput(set: (value: string) => void) {
  return {
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      set(trimLeading(e.target.value)),
    onBlur: (e: React.FocusEvent<HTMLInputElement>) => {
      const trimmed = e.target.value.trim();
      if (trimmed !== e.target.value) set(trimmed);
    },
  };
}
