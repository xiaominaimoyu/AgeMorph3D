/** Piecewise linear blend between neighboring age anchors; weights sum to one. */
export function getAgeWeights(
  age: number,
  ages: readonly number[] = [20, 45, 70],
): number[] {
  if (!Number.isFinite(age)) throw new Error("年龄必须是有限数值。");
  if (
    !ages.length ||
    ages.some(
      (value, index) =>
        !Number.isFinite(value) || (index > 0 && value <= ages[index - 1]),
    )
  ) {
    throw new Error("年龄锚点必须是严格递增的有限数值。");
  }
  const result = ages.map(() => 0);
  if (age <= ages[0]) result[0] = 1;
  else if (age >= ages[ages.length - 1]) result[result.length - 1] = 1;
  else {
    const right = ages.findIndex((value) => value >= age);
    const factor = (age - ages[right - 1]) / (ages[right] - ages[right - 1]);
    result[right - 1] = 1 - factor;
    result[right] = factor;
  }
  return result;
}
