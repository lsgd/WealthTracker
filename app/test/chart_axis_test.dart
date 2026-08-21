import 'package:flutter_test/flutter_test.dart';
import 'package:wealth_tracker/core/utils/chart_axis.dart';
import 'package:wealth_tracker/core/utils/formatters.dart';

void main() {
  group('niceAxis', () {
    test('produces exactly 4 intervals with nice steps', () {
      final axis = niceAxis(0, 31000);
      expect(axis.min, 0);
      expect(axis.interval, 10000);
      expect(axis.max, 40000);
    });

    test('covers the value range', () {
      for (final max in [1.0, 950.0, 31000.0, 2825058.0, 9e7]) {
        final axis = niceAxis(0, max);
        expect(axis.max, greaterThanOrEqualTo(max));
        expect(((axis.max - axis.min) / axis.interval).round(), 4);
      }
    });
  });

  group('formatChartAxisValue with nice steps', () {
    /// The axis tick labels for a 0..max range.
    List<String> labelsFor(double max) {
      final axis = niceAxis(0, max);
      final labels = <String>[];
      for (var v = axis.min; v <= axis.max + 1e-9; v += axis.interval) {
        labels.add(formatChartAxisValue(v, step: axis.interval));
      }
      return labels;
    }

    test('labels are unique — no duplicated tick text', () {
      for (final max in [950.0, 31000.0, 2825058.0, 9e7, 12345.0]) {
        final labels = labelsFor(max);
        expect(labels.toSet().length, labels.length,
            reason: 'duplicate labels for range 0..$max: $labels');
      }
    });

    test('fractional M steps use 2 decimals, never a wrong rounding', () {
      // Step 2.5M: "2.50M", not "3M".
      expect(formatChartAxisValue(2500000, step: 2500000), '2.50M');
      expect(formatChartAxisValue(7500000, step: 2500000), '7.50M');
      // Whole-unit steps stay integer.
      expect(formatChartAxisValue(2000000, step: 1000000), '2M');
      expect(formatChartAxisValue(30000, step: 10000), '30K');
      // Mixed-unit axis: the K tick below 1M still formats in K.
      expect(formatChartAxisValue(500000, step: 250000), '500K');
    });
  });
}
