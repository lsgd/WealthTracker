import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../../data/models/spending.dart';
import '../providers/spending_provider.dart';
import '../widgets/transactions_tab.dart';
import 'spending_config_screen.dart';

/// Category palette. Deliberately excludes the income color so the income line
/// never shares a color with a category (same rule as the web UI).
const _categoryColors = <Color>[
  Color(0xFF4F8CFF),
  Color(0xFFA3E635),
  Color(0xFFFBBF24),
  Color(0xFFF87171),
  Color(0xFFA78BFA),
  Color(0xFFFB923C),
  Color(0xFF38BDF8),
  Color(0xFFE879F9),
];
const _incomeColor = Color(0xFF34D399);
const _uncategorizedColor = Color(0xFF5B6270);
const _uncategorizedLabel = 'Uncategorized';

const _ranges = [6, 12, 24];

class SpendingScreen extends ConsumerWidget {
  const SpendingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final report = ref.watch(spendingReportProvider);

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Spending'),
          actions: [
            IconButton(
              icon: const Icon(Icons.tune),
              tooltip: 'Rules and AI',
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                    builder: (_) => const SpendingConfigScreen()),
              ),
            ),
          ],
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Insights'),
              Tab(text: 'Transactions'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            RefreshIndicator(
              onRefresh: () async => ref.refresh(spendingReportProvider.future),
              child: report.when(
                data: (data) => data.months.isEmpty
                    ? const _EmptyState()
                    : _SpendingBody(report: data),
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (e, _) => _ErrorState(message: e.toString()),
              ),
            ),
            const TransactionsTab(),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: const [
        SizedBox(height: 120),
        Center(child: Text('No transactions yet.')),
      ],
    );
  }
}

class _ErrorState extends StatelessWidget {
  final String message;
  const _ErrorState({required this.message});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 80),
        Icon(Icons.error_outline,
            color: Theme.of(context).colorScheme.error, size: 40),
        const SizedBox(height: 12),
        Text(message, textAlign: TextAlign.center),
      ],
    );
  }
}

class _SpendingBody extends ConsumerWidget {
  final SpendingReport report;

  const _SpendingBody({required this.report});

  /// Categories in report order, optionally without the uncategorized bucket.
  List<String> _visibleCategories(bool showUncategorized) => report.categories
      .where((c) => showUncategorized || c != _uncategorizedLabel)
      .toList();

  Color _colorFor(String category) {
    if (category == _uncategorizedLabel) return _uncategorizedColor;
    final index = report.categories.indexOf(category);
    return _categoryColors[(index < 0 ? 0 : index) % _categoryColors.length];
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(spendingModeProvider);
    final range = ref.watch(spendingRangeProvider);
    final showUncategorized = ref.watch(spendingShowUncategorizedProvider);
    final selectedMonth = ref.watch(spendingSelectedMonthProvider);

    final categories = _visibleCategories(showUncategorized);
    final month = report.months.firstWhere(
      (m) => m.month == selectedMonth,
      orElse: () => report.months.last,
    );

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        _ControlsCard(
          mode: mode,
          range: range,
          showUncategorized: showUncategorized,
          average: report.averageExpenses,
          currency: report.baseCurrency,
        ),
        const SizedBox(height: 12),
        _MonthlyChartCard(
          report: report,
          categories: categories,
          colorFor: _colorFor,
          onMonthSelected: (m) =>
              ref.read(spendingSelectedMonthProvider.notifier).set(m),
        ),
        const SizedBox(height: 12),
        _BreakdownCard(
          report: report,
          month: month,
          showUncategorized: showUncategorized,
          colorFor: _colorFor,
        ),
      ],
    );
  }
}

class _ControlsCard extends ConsumerWidget {
  final String mode;
  final int range;
  final bool showUncategorized;
  final double average;
  final String currency;

  const _ControlsCard({
    required this.mode,
    required this.range,
    required this.showUncategorized,
    required this.average,
    required this.currency,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(
                  value: 'normalized',
                  label: Text('Normalized'),
                  tooltip: 'Yearly bills spread across their months',
                ),
                ButtonSegment(
                  value: 'actual',
                  label: Text('Actual'),
                  tooltip: 'Raw cash flow per month',
                ),
              ],
              selected: {mode},
              onSelectionChanged: (s) =>
                  ref.read(spendingModeProvider.notifier).set(s.first),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                ..._ranges.map((r) => Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        label: Text('${r}m'),
                        selected: range == r,
                        onSelected: (_) =>
                            ref.read(spendingRangeProvider.notifier).set(r),
                      ),
                    )),
                const Spacer(),
                FilterChip(
                  label: const Text('Uncat.'),
                  tooltip: 'Show or hide uncategorized spending',
                  selected: showUncategorized,
                  onSelected: (v) => ref
                      .read(spendingShowUncategorizedProvider.notifier)
                      .set(v),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Average monthly spending ($mode): '
              '${formatCurrency(average, currency)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _MonthlyChartCard extends StatelessWidget {
  final SpendingReport report;
  final List<String> categories;
  final Color Function(String) colorFor;
  final ValueChanged<String> onMonthSelected;

  const _MonthlyChartCard({
    required this.report,
    required this.categories,
    required this.colorFor,
    required this.onMonthSelected,
  });

  @override
  Widget build(BuildContext context) {
    final months = report.months;
    final maxExpense = months.fold<double>(0, (max, m) {
      final visible = categories.fold<double>(
          0, (sum, c) => sum + (m.byCategory[c] ?? 0));
      return visible > max ? visible : max;
    });

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 16, 16, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 8, bottom: 12),
              child: Text('Monthly spending',
                  style: Theme.of(context).textTheme.titleMedium),
            ),
            SizedBox(
              height: 240,
              child: BarChart(
                BarChartData(
                  maxY: maxExpense <= 0 ? 1 : maxExpense * 1.15,
                  barTouchData: BarTouchData(
                    touchCallback: (event, response) {
                      if (event.isInterestedForInteractions &&
                          response?.spot != null) {
                        onMonthSelected(
                            months[response!.spot!.touchedBarGroupIndex].month);
                      }
                    },
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipItem: (group, groupIndex, rod, rodIndex) {
                        final m = months[groupIndex];
                        return BarTooltipItem(
                          '${m.month}\n'
                          '${formatCurrency(m.expenses, report.baseCurrency)}',
                          Theme.of(context).textTheme.bodySmall ??
                              const TextStyle(),
                        );
                      },
                    ),
                  ),
                  gridData: FlGridData(
                    show: true,
                    drawVerticalLine: false,
                    getDrawingHorizontalLine: (_) => FlLine(
                      color: Theme.of(context).dividerColor.withValues(alpha: 0.3),
                      strokeWidth: 1,
                    ),
                  ),
                  borderData: FlBorderData(show: false),
                  titlesData: FlTitlesData(
                    topTitles:
                        const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    rightTitles:
                        const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 46,
                        getTitlesWidget: (value, meta) => Text(
                          formatChartAxisValue(value),
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 28,
                        getTitlesWidget: (value, meta) {
                          final index = value.toInt();
                          if (index < 0 || index >= months.length) {
                            return const SizedBox.shrink();
                          }
                          // Only every other label on long ranges.
                          if (months.length > 12 && index.isOdd) {
                            return const SizedBox.shrink();
                          }
                          return Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              months[index].month.substring(2),
                              style: Theme.of(context).textTheme.labelSmall,
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                  barGroups: [
                    for (var i = 0; i < months.length; i++)
                      BarChartGroupData(
                        x: i,
                        barRods: [
                          BarChartRodData(
                            toY: categories.fold<double>(
                                0,
                                (sum, c) =>
                                    sum + (months[i].byCategory[c] ?? 0)),
                            width: months.length > 12 ? 8 : 14,
                            borderRadius:
                                const BorderRadius.vertical(top: Radius.circular(3)),
                            rodStackItems: _stackFor(months[i]),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
            _Legend(categories: categories, colorFor: colorFor),
          ],
        ),
      ),
    );
  }

  /// Stack segments for one month, in report category order.
  List<BarChartRodStackItem> _stackFor(SpendingMonth month) {
    final items = <BarChartRodStackItem>[];
    var from = 0.0;
    for (final category in categories) {
      final value = month.byCategory[category] ?? 0;
      if (value <= 0) continue;
      items.add(BarChartRodStackItem(from, from + value, colorFor(category)));
      from += value;
    }
    return items;
  }
}

class _Legend extends StatelessWidget {
  final List<String> categories;
  final Color Function(String) colorFor;

  const _Legend({required this.categories, required this.colorFor});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 12,
      runSpacing: 4,
      children: [
        for (final category in categories)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  color: colorFor(category),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(width: 4),
              Text(category, style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
      ],
    );
  }
}

class _BreakdownCard extends ConsumerWidget {
  final SpendingReport report;
  final SpendingMonth month;
  final bool showUncategorized;
  final Color Function(String) colorFor;

  const _BreakdownCard({
    required this.report,
    required this.month,
    required this.showUncategorized,
    required this.colorFor,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entries = month.byCategory.entries
        .where((e) => showUncategorized || e.key != _uncategorizedLabel)
        .toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final total = entries.fold<double>(0, (sum, e) => sum + e.value);

    final index = report.months.indexWhere((m) => m.month == month.month);
    final currency = report.baseCurrency;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Breakdown · ${month.month}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_left),
                  tooltip: 'Previous month',
                  onPressed: index > 0
                      ? () => ref
                          .read(spendingSelectedMonthProvider.notifier)
                          .set(report.months[index - 1].month)
                      : null,
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_right),
                  tooltip: 'Next month',
                  onPressed: index >= 0 && index < report.months.length - 1
                      ? () => ref
                          .read(spendingSelectedMonthProvider.notifier)
                          .set(report.months[index + 1].month)
                      : null,
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (entries.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 32),
                child: Center(child: Text('No spending in this month.')),
              )
            else ...[
              SizedBox(
                height: 180,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    PieChart(
                      PieChartData(
                        sectionsSpace: 2,
                        centerSpaceRadius: 52,
                        sections: [
                          for (final e in entries)
                            PieChartSectionData(
                              value: e.value,
                              color: colorFor(e.key),
                              radius: 26,
                              showTitle: false,
                            ),
                        ],
                      ),
                    ),
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          formatCurrencyCompact(total, currency),
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        Text(
                          month.month,
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              for (final e in entries)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(
                    children: [
                      Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(
                          color: colorFor(e.key),
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(child: Text(e.key)),
                      Text(formatCurrency(e.value, currency)),
                      const SizedBox(width: 10),
                      SizedBox(
                        width: 46,
                        child: Text(
                          total > 0
                              ? '${(e.value / total * 100).toStringAsFixed(1)}%'
                              : '0.0%',
                          textAlign: TextAlign.right,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                    ],
                  ),
                ),
              const Divider(height: 20),
              Row(
                children: [
                  Expanded(
                    child: Text('Income',
                        style: Theme.of(context).textTheme.bodyMedium),
                  ),
                  Text(
                    formatCurrency(month.income, currency),
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium
                        ?.copyWith(color: _incomeColor),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
