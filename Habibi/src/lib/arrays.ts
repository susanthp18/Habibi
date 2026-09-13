/**
 * `a[i]` for an index the caller has already bounded (a loop over `length`,
 * `length - 1` after an emptiness check). Under `noUncheckedIndexedAccess`
 * every subscript reads as `T | undefined`; this is the one place that says
 * "in range, or a bug" instead of threading `?? 0` through arithmetic.
 */
export function at<T>(a: ArrayLike<T>, i: number): T {
  const v = a[i];
  if (v === undefined) throw new RangeError(`index ${i} out of range (length ${a.length})`);
  return v;
}
