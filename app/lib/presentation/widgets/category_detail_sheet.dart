import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../core/utils/chart_axis.dart';
import '../../core/utils/formatters.dart';
import '../../core/utils/periods.dart';
import '../../data/models/spending.dart';

/// One category across the whole loaded window: what it costs per period, on
/// average, and in total.
///
/// The breakdown answers "where did this period's money go"; this answers "is
/// this normal", which is the question that follows.
class CategoryDetailSheet extends StatelessWidget {
  final String category;
  final Color color;
  final SpendingReport report;

  /// The period being inspected — it stands out from its own history.
  final String? selectedPeriod;
  final ValueChanged<String> onSelectPeriod;

  /// Opens the transaction list narrowed to this category, when the caller can
  /// get there (the Insights tab can; a sheet opened from elsewhere cannot).
  final VoidCallback? onShowTransactions;

  const CategoryDetailSheet({
    super.key,
    required this.category,
    required this.color,
    required this.report,
    required this.selectedPeriod,
    required this.onSelectPeriod,
    this.onShowTransactions,
  });

  static Future<void> show(
    BuildContext context, {
    required String category,
    required Color color,
    required SpendingReport report,
    required String? selectedPeriod,
    required ValueChanged<String> onSelectPeriod,
    VoidCallback? onShowTransactions,
  }) {
    return showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => CategoryDetailSheet(
        category: category,
        color: color,
        report: report,
        selectedPeriod: selectedPeriod,
        onSelectPeriod: onSelectPeriod,
        onShowTransactions: onShowTransactions,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final currency = report.baseCurrency;
    final noun = periodNoun(report.granularity);
    final series = [
      for (final period in report.months)
        (period: period.month, amount: period.byCategory[category] ?? 0.0),
    ];

    final total = series.fold<double>(0, (sum, s) => sum + s.amount);
    // Averaged over the completed periods that actually had spending: the
    // running one is partial, and the empty ones before a category existed are
    // absence of data, not a period of spending nothing.
    final spent = series
        .take(series.length > 1 ? series.length - 1 : series.length)
        .where((s) => s.amount > 0)
        .toList();
    final average = spent.isEmpty
        ? 0.0
        : spent.fold<double>(0, (sum, s) => sum + s.amount) / spent.length;
    final biggest = series.isEmpty
        ? (period: '', amount: 0.0)
        : series.reduce((max, s) => s.amount > max.amount ? s : max);

    final maxAmount =
        series.fold<double>(0, (max, s) => s.amount > max ? s.amount : max);
    final axis = niceAxis(0, maxAmount <= 0 ? 1 : maxAmount * 1.1);
    final labelEvery = (series.length / 5).ceil().clamp(1, 100);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    color: color,
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(category, style: theme.textTheme.titleMedium),
                ),
                if (onShowTransactions != null)
                  TextButton.icon(
                    onPressed: () {
                      Navigator.of(context).pop();
                      onShowTransactions!();
                    },
                    icon: const Icon(Icons.receipt_long, size: 18),
                    label: const Text('Transactions'),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                _Stat(
                  label: 'Total (${series.length} ${noun}s)',
                  value: formatCurrency(total, currency),
                ),
                _Stat(
                  label: 'Average per $noun',
                  value: formatCurrency(average, currency),
                ),
                _Stat(
                  label: 'Highest',
                  value: formatCurrency(biggest.amount, currency),
                  hint: biggest.period.isEmpty
                      ? null
                      : formatPeriod(biggest.period),
                ),
              ],
            ),
            const SizedBox(height: 20),
            SizedBox(
              height: 180,
              child: BarChart(
                BarChartData(
                  maxY: axis.max,
                  barTouchData: BarTouchData(
                    touchCallback: (event, response) {
                      if (event.isInterestedForInteractions &&
                          response?.spot != null) {
                        final index = response!.spot!.touchedBarGroupIndex;
                        if (index >= 0 && index < series.length) {
                          onSelectPeriod(series[index].period);
                          Navigator.of(context).pop();
                        }
                      }
                    },
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipItem: (group, groupIndex, rod, rodIndex) =>
                          BarTooltipItem(
                        '${formatPeriod(series[groupIndex].period)}\n'
                        '${formatCurrencyExact(series[groupIndex].amount, currency)}',
                        theme.textTheme.bodySmall ?? const TextStyle(),
                      ),
                    ),
                  ),
                  gridData: FlGridData(
                    show: true,
                    drawVerticalLine: false,
                    horizontalInterval: axis.interval,
                    getDrawingHorizontalLine: (_) => FlLine(
                      color: theme.dividerColor.withValues(alpha: 0.3),
                      strokeWidth: 1,
                    ),
                  ),
                  borderData: FlBorderData(show: false),
                  titlesData: FlTitlesData(
                    topTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false)),
                    rightTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false)),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 44,
                        interval: axis.interval,
                        getTitlesWidget: (value, meta) => FittedBox(
                          fit: BoxFit.scaleDown,
                          child: Text(
                            formatChartAxisValue(value, step: axis.interval),
                            maxLines: 1,
                            softWrap: false,
                            style: theme.textTheme.labelSmall,
                          ),
                        ),
                      ),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 26,
                        getTitlesWidget: (value, meta) {
                          final index = value.toInt();
                          if (index < 0 ||
                              index >= series.length ||
                              index % labelEvery != 0) {
                            return const SizedBox.shrink();
                          }
                          return Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              formatPeriodShort(series[index].period),
                              style: theme.textTheme.labelSmall,
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                  barGroups: [
                    for (var i = 0; i < series.length; i++)
                      BarChartGroupData(
                        x: i,
                        barRods: [
                          BarChartRodData(
                            toY: series[i].amount,
                            width: series.length > 12 ? 8 : 14,
                            borderRadius: const BorderRadius.vertical(
                                top: Radius.circular(3)),
                            color: selectedPeriod == null ||
                                    series[i].period == selectedPeriod
                                ? color
                                : color.withValues(alpha: 0.45),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final String? hint;

  const _Stat({required this.label, required this.value, this.hint});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 2),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(value, style: theme.textTheme.titleSmall),
          ),
          if (hint != null)
            Text(
              hint!,
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
        ],
      ),
    );
  }
}
