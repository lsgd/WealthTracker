/// Period labels for the spending report, matching the web client.
///
/// The report labels a period ``YYYY-MM``, ``YYYY-Qn`` or ``YYYY`` depending on
/// the granularity it was asked for, and the transaction endpoint accepts the
/// same three shapes — so a label picked here can be handed straight to the
/// list without translation.
library;

import 'package:intl/intl.dart';

const granularities = <String>['month', 'quarter', 'year'];

/// How much history the trend chart offers, per granularity.
const historyChoices = <String, List<int>>{
  'month': [6, 12, 24],
  'quarter': [4, 8, 12],
  'year': [3, 5, 10],
};

/// Periods averaged for the "vs average" comparison.
const averageWindow = 6;

/// Default amount of history when switching to [granularity].
int defaultHistory(String granularity) =>
    (historyChoices[granularity] ?? historyChoices['month']!)[1];

/// The word for one period, for labels like "vs last quarter".
String periodNoun(String granularity) =>
    granularities.contains(granularity) ? granularity : 'month';

/// '2026-08' -> 'August 2026', '2026-Q3' -> 'Q3 2026', '2026' -> '2026'.
String formatPeriod(String label) {
  if (RegExp(r'^\d{4}$').hasMatch(label)) return label;
  final parts = label.split('-');
  if (parts.length < 2) return label;
  if (parts[1].startsWith('Q')) return '${parts[1]} ${parts[0]}';
  final month = int.tryParse(parts[1]);
  if (month == null) return label;
  return DateFormat('MMMM yyyy').format(DateTime(int.parse(parts[0]), month));
}

/// Compact form for chart axes, where a dozen labels share the width.
String formatPeriodShort(String label) {
  if (RegExp(r'^\d{4}$').hasMatch(label)) return label;
  final parts = label.split('-');
  if (parts.length < 2) return label;
  final year = parts[0].substring(2);
  if (parts[1].startsWith('Q')) return "${parts[1]} '$year";
  final month = int.tryParse(parts[1]);
  if (month == null) return label;
  final name = DateFormat('MMM').format(DateTime(int.parse(parts[0]), month));
  return "$name '$year";
}
