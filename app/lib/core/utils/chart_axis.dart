import 'dart:math' as math;

/// A rounded y-axis: min/max aligned to a "nice" tick interval so fl_chart
/// draws evenly spaced, non-overlapping, non-duplicate labels. Shared by the
/// simulation and spending charts (the wealth chart has its own older copy of
/// the same 1-2.5-5 logic inline).
class NiceAxis {
  final double min;
  final double max;
  final double interval;

  const NiceAxis({required this.min, required this.max, required this.interval});
}

/// Compute a [NiceAxis] covering [minValue]..[maxValue] with exactly
/// [intervals] steps in the 1-2.5-5 sequence (floored at 100).
NiceAxis niceAxis(double minValue, double maxValue, {int intervals = 4}) {
  if (maxValue <= minValue) maxValue = minValue + 1;
  final range = maxValue - minValue;
  var step = _niceStep(range / intervals);

  var roundedMin = (minValue / step).floorToDouble() * step;
  var roundedMax = (maxValue / step).ceilToDouble() * step;
  var count = ((roundedMax - roundedMin) / step).round();

  // Bump to the next nice step if floor/ceil pushed us over the target count.
  while (count > intervals) {
    step = _nextNiceStep(step);
    roundedMin = (minValue / step).floorToDouble() * step;
    roundedMax = (maxValue / step).ceilToDouble() * step;
    count = ((roundedMax - roundedMin) / step).round();
  }
  // Extend max to fill exactly the target count.
  while (count < intervals) {
    roundedMax += step;
    count++;
  }

  return NiceAxis(min: roundedMin, max: roundedMax, interval: step);
}

/// Round up to a "nice" step in the 1-2.5-5 sequence at each decade,
/// floored at 100. Produces clean axis labels: 100, 250, 500, 1k, 2.5k, 5k, ...
double _niceStep(double rawStep) {
  if (rawStep <= 100) return 100;
  final magnitude =
      math.pow(10, (math.log(rawStep) / math.ln10).floor()).toDouble();
  final normalized = rawStep / magnitude;
  final double mantissa;
  if (normalized <= 1) {
    mantissa = 1;
  } else if (normalized <= 2.5) {
    mantissa = 2.5;
  } else if (normalized <= 5) {
    mantissa = 5;
  } else {
    mantissa = 10;
  }
  return mantissa * magnitude;
}

/// Next nice step after the given one (e.g. 250 -> 500, 500 -> 1000).
double _nextNiceStep(double step) {
  final magnitude =
      math.pow(10, (math.log(step) / math.ln10).floor()).toDouble();
  final normalized = step / magnitude;
  if (normalized < 2.5) return 2.5 * magnitude;
  if (normalized < 5) return 5 * magnitude;
  return 10 * magnitude;
}
