import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/chart_axis.dart';
import '../../core/utils/formatters.dart';
import '../../core/utils/periods.dart';
import '../../data/models/spending.dart';
import '../providers/spending_provider.dart';
import '../widgets/category_detail_sheet.dart';
import '../widgets/transactions_tab.dart';
import 'spending_config_screen.dart';

/// Category palette. Excludes the income and uncategorized colors so neither
/// shares a color with a category. Eight hues cover the wheel; the rest are
/// deep variants, since past that point only lightness can still tell two
/// categories apart. With eight, a ninth category wrapped around and became a
/// twin of the first. Same list and order as the web UI.
const _categoryColors = <Color>[
  Color(0xFF4F8CFF),
  Color(0xFFFB923C),
  Color(0xFFA3E635),
  Color(0xFFE879F9),
  Color(0xFFFBBF24),
  Color(0xFF38BDF8),
  Color(0xFFF87171),
  Color(0xFFA78BFA),
  Color(0xFFF472B6),
  Color(0xFF0E7490),
  Color(0xFF4D7C0F),
  Color(0xFFC2410C),
  Color(0xFF6D28D9),
  Color(0xFFBE123C),
];
/// Shade applied per lap through the palette: a fraction towards white when
/// positive, towards black when negative. Past fourteen categories the colors
/// would otherwise repeat exactly; the web additionally hatches them, which a
/// stacked bar rod here cannot do (fl_chart takes a flat color), so the shade
/// is what keeps them apart. Both clients compute it the same way, so a
/// category's color matches across them.
const _lapShades = [0.0, 0.4, -0.4, 0.65];

/// Mixes [color] towards white ([amount] > 0) or black ([amount] < 0).
Color _shade(Color color, double amount) {
  if (amount == 0) return color;
  return Color.lerp(color, amount > 0 ? Colors.white : Colors.black,
      amount.abs())!;
}

const _incomeColor = Color(0xFF34D399);
const _uncategorizedColor = Color(0xFF5B6270);
const _uncategorizedLabel = 'Uncategorized';

/// A value against the period before it and against the trailing average.
///
/// Both on purpose: period-on-period is noisy when a yearly bill lands (a 300%
/// jump that means nothing), while the average says whether this period is
/// genuinely out of line. Null where there is nothing to compare against — a
/// period before the data starts is absence of history, not a period of
/// spending nothing, and averaging those in turns every delta into +400%.
typedef Comparison = ({double? vsPrevious, double? vsAverage});

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
    // Counted without the uncategorized bucket, which holds no palette slot —
    // otherwise the same category gets different colors here and on the web.
    final index = report.categories
        .where((c) => c != _uncategorizedLabel)
        .toList()
        .indexOf(category);
    if (index < 0) return _uncategorizedColor;
    return _shade(
      _categoryColors[index % _categoryColors.length],
      _lapShades[(index ~/ _categoryColors.length) % _lapShades.length],
    );
  }

  /// Spending of one period, matching what the charts show: with the
  /// uncategorized bucket switched off, every number on screen refers to the
  /// same set of transactions.
  double _spentIn(SpendingMonth month, bool showUncategorized) =>
      showUncategorized
          ? month.expenses
          : month.expenses - (month.byCategory[_uncategorizedLabel] ?? 0);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(spendingModeProvider);
    final granularity = ref.watch(spendingGranularityProvider);
    final range = ref.watch(spendingRangeProvider);
    final showUncategorized = ref.watch(spendingShowUncategorizedProvider);
    final selectedMonth = ref.watch(spendingSelectedMonthProvider);

    final categories = _visibleCategories(showUncategorized);
    var index = report.months.indexWhere((m) => m.month == selectedMonth);
    if (index < 0) index = report.months.length - 1;
    final month = report.months[index];
    final noun = periodNoun(report.granularity);

    // Only the completed periods before this one, newest last.
    final trailing = report.months
        .sublist(index - averageWindow < 0 ? 0 : index - averageWindow, index);

    Comparison compare(double value, double Function(SpendingMonth) pick) {
      final previous = index > 0 ? pick(report.months[index - 1]) : null;
      final seen = trailing.map(pick).where((v) => v != 0).toList();
      final average = seen.isEmpty
          ? null
          : seen.fold<double>(0, (sum, v) => sum + v) / seen.length;
      return (
        vsPrevious: previous == null || previous == 0
            ? null
            : (value - previous) / previous.abs(),
        vsAverage:
            average == null ? null : (value - average) / average.abs(),
      );
    }

    final spent = _spentIn(month, showUncategorized);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        _PeriodCard(
          granularity: granularity,
          mode: mode,
          range: range,
          showUncategorized: showUncategorized,
          periods: [for (final m in report.months) m.month],
          selected: month.month,
        ),
        const SizedBox(height: 12),
        _SummaryCard(
          currency: report.baseCurrency,
          noun: noun,
          // The running period is only a partial total, and reading it as a
          // finished one makes every comparison look like a collapse.
          partial: index == report.months.length - 1,
          spent: spent,
          income: month.income,
          spentComparison:
              compare(spent, (m) => _spentIn(m, showUncategorized)),
          incomeComparison: compare(month.income, (m) => m.income),
          netComparison: compare(month.income - spent,
              (m) => m.income - _spentIn(m, showUncategorized)),
          budgets: report.budgets,
          byCategory: month.byCategory,
          showUncategorized: showUncategorized,
        ),
        const SizedBox(height: 12),
        _MonthlyChartCard(
          report: report,
          categories: categories,
          selectedPeriod: month.month,
          colorFor: _colorFor,
          onMonthSelected: (m) =>
              ref.read(spendingSelectedMonthProvider.notifier).set(m),
        ),
        const SizedBox(height: 12),
        _BreakdownCard(
          report: report,
          month: month,
          previous: index > 0 ? report.months[index - 1] : null,
          trailing: trailing,
          showUncategorized: showUncategorized,
          colorFor: _colorFor,
        ),
      ],
    );
  }
}

/// The one period control for the whole screen: chart, breakdown and the
/// transaction list all follow it.
///
/// Before this, the period lived in two places — a range chip here and a month
/// dropdown in the transaction filter — and they could disagree, so the
/// breakdown showed August while the list showed everything.
class _PeriodCard extends ConsumerWidget {
  final String granularity;
  final String mode;
  final int range;
  final bool showUncategorized;

  /// Every period the report covers, oldest first.
  final List<String> periods;
  final String selected;

  const _PeriodCard({
    required this.granularity,
    required this.mode,
    required this.range,
    required this.showUncategorized,
    required this.periods,
    required this.selected,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final index = periods.indexOf(selected);
    final noun = periodNoun(granularity);
    final counts = historyChoices[granularity] ?? historyChoices['month']!;

    void select(String period) =>
        ref.read(spendingSelectedMonthProvider.notifier).set(period);

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                showSelectedIcon: false,
                segments: const [
                  ButtonSegment(value: 'month', label: Text('Month')),
                  ButtonSegment(value: 'quarter', label: Text('Quarter')),
                  ButtonSegment(value: 'year', label: Text('Year')),
                ],
                selected: {granularity},
                onSelectionChanged: (s) => ref
                    .read(spendingGranularityProvider.notifier)
                    .set(s.first),
              ),
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                IconButton(
                  icon: const Icon(Icons.chevron_left),
                  tooltip: 'Previous $noun',
                  onPressed:
                      index > 0 ? () => select(periods[index - 1]) : null,
                ),
                Expanded(
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      isExpanded: true,
                      value: selected,
                      // Newest first: the recent periods are the ones anyone
                      // scrolls to, and they would otherwise sit at the bottom.
                      items: [
                        for (final period in periods.reversed)
                          DropdownMenuItem(
                            value: period,
                            child: Text(
                              formatPeriod(period),
                              textAlign: TextAlign.center,
                            ),
                          ),
                      ],
                      onChanged: (value) {
                        if (value != null) select(value);
                      },
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_right),
                  tooltip: 'Next $noun',
                  onPressed: index >= 0 && index < periods.length - 1
                      ? () => select(periods[index + 1])
                      : null,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                ...counts.map((count) => Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        label: Text('$count'),
                        tooltip: 'Show $count ${noun}s of history',
                        selected: range == count,
                        onSelected: (_) =>
                            ref.read(spendingRangeProvider.notifier).set(count),
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
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                showSelectedIcon: false,
                segments: const [
                  ButtonSegment(
                    value: 'normalized',
                    label: Text('Normalized'),
                    tooltip: 'Yearly bills spread across the months they cover',
                  ),
                  ButtonSegment(
                    value: 'actual',
                    label: Text('Actual'),
                    tooltip: 'Raw cash flow, each bill when it was paid',
                  ),
                ],
                selected: {mode},
                onSelectionChanged: (s) =>
                    ref.read(spendingModeProvider.notifier).set(s.first),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Spending, income and net for the selected period, each against the period
/// before and against the trailing average, plus how the budget is holding up.
class _SummaryCard extends StatelessWidget {
  final String currency;
  final String noun;
  final bool partial;
  final double spent;
  final double income;
  final Comparison spentComparison;
  final Comparison incomeComparison;
  final Comparison netComparison;
  final Map<String, double> budgets;
  final Map<String, double> byCategory;
  final bool showUncategorized;

  const _SummaryCard({
    required this.currency,
    required this.noun,
    required this.partial,
    required this.spent,
    required this.income,
    required this.spentComparison,
    required this.incomeComparison,
    required this.netComparison,
    required this.budgets,
    required this.byCategory,
    required this.showUncategorized,
  });

  /// Sum of the budgets of the categories on screen, or null when none is set.
  double? get _budgetTotal {
    final relevant = budgets.entries
        .where((e) => showUncategorized || e.key != _uncategorizedLabel);
    if (relevant.isEmpty) return null;
    return relevant.fold<double>(0, (sum, e) => sum + e.value);
  }

  /// How much of the period's spending falls in categories that have a budget
  /// — without it, "CHF 400 left" reads as if it covered everything.
  double get _budgetedShare {
    if (spent <= 0) return 100;
    final budgeted = budgets.keys
        .fold<double>(0, (sum, name) => sum + (byCategory[name] ?? 0));
    return budgeted / spent * 100;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final budgetTotal = _budgetTotal;
    final share = _budgetedShare;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _SummaryTile(
                  label: 'Spent',
                  value: spent,
                  currency: currency,
                  comparison: spentComparison,
                  moreIsBetter: false,
                  partial: partial,
                ),
                _SummaryTile(
                  label: 'Income',
                  value: income,
                  currency: currency,
                  comparison: incomeComparison,
                  moreIsBetter: true,
                  partial: partial,
                ),
                _SummaryTile(
                  label: 'Net',
                  value: income - spent,
                  currency: currency,
                  comparison: netComparison,
                  moreIsBetter: true,
                  partial: partial,
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Compared with the previous $noun and the average of the '
              'last $averageWindow.',
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            if (budgetTotal != null) ...[
              const Divider(height: 20),
              Text.rich(
                TextSpan(children: [
                  TextSpan(
                    text: spent > budgetTotal
                        ? formatCurrency(spent - budgetTotal, currency)
                        : formatCurrency(budgetTotal - spent, currency),
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: spent > budgetTotal
                          ? theme.colorScheme.error
                          : _incomeColor,
                    ),
                  ),
                  TextSpan(
                    text: spent > budgetTotal
                        ? ' over the ${formatCurrency(budgetTotal, currency)} '
                            'budget for this $noun'
                        : ' left of the ${formatCurrency(budgetTotal, currency)} '
                            'budget for this $noun',
                  ),
                ]),
                style: theme.textTheme.bodySmall,
              ),
              if (share < 99.5)
                Text(
                  'Budgets cover ${share.toStringAsFixed(0)}% of what you spend.',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SummaryTile extends StatelessWidget {
  final String label;
  final double value;
  final String currency;
  final Comparison comparison;

  /// Whether more is good: net and income yes, spending no.
  final bool moreIsBetter;
  final bool partial;

  const _SummaryTile({
    required this.label,
    required this.value,
    required this.currency,
    required this.comparison,
    required this.moreIsBetter,
    required this.partial,
  });

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
            child: Text(
              formatCurrency(value, currency),
              maxLines: 1,
              style: theme.textTheme.titleSmall,
            ),
          ),
          if (partial)
            Text(
              'so far',
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          const SizedBox(height: 2),
          _Delta(
            change: comparison.vsPrevious,
            moreIsBetter: moreIsBetter,
            suffix: 'vs last',
          ),
          _Delta(
            change: comparison.vsAverage,
            moreIsBetter: moreIsBetter,
            suffix: 'vs avg',
          ),
        ],
      ),
    );
  }
}

/// One comparison: the arrow shows the direction, the color says whether that
/// direction is welcome — spending more is bad, earning more is good.
class _Delta extends StatelessWidget {
  final double? change;
  final bool moreIsBetter;
  final String suffix;

  const _Delta({
    required this.change,
    required this.moreIsBetter,
    required this.suffix,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.labelSmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);

    if (change == null) {
      return Text('— $suffix', style: muted);
    }
    final percent = (change! * 100).round();
    if (percent == 0) {
      return Text('flat $suffix', style: muted);
    }
    final good = (percent > 0) == moreIsBetter;
    final color = good ? _incomeColor : theme.colorScheme.error;
    return Row(
      children: [
        Icon(percent > 0 ? Icons.arrow_upward : Icons.arrow_downward,
            size: 11, color: color),
        Expanded(
          child: FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              '${percent.abs()}% $suffix',
              maxLines: 1,
              style: theme.textTheme.labelSmall?.copyWith(color: color),
            ),
          ),
        ),
      ],
    );
  }
}

class _MonthlyChartCard extends StatelessWidget {
  final SpendingReport report;
  final List<String> categories;
  final String selectedPeriod;
  final Color Function(String) colorFor;
  final ValueChanged<String> onMonthSelected;

  const _MonthlyChartCard({
    required this.report,
    required this.categories,
    required this.selectedPeriod,
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
    // Nice ticks: without an explicit interval fl_chart adds an extra label at
    // maxY, which collided with the tick below it (e.g. "31K" on top of "30K").
    final axis = niceAxis(0, maxExpense <= 0 ? 1 : maxExpense * 1.1);
    // At most ~6 x-labels, regardless of range.
    final labelEvery = (months.length / 6).ceil();

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 16, 16, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 8, bottom: 12),
              child: Text(
                'Spending per ${periodNoun(report.granularity)}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            SizedBox(
              height: 240,
              child: BarChart(
                BarChartData(
                  maxY: axis.max,
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
                          '${formatPeriod(m.month)}\n'
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
                    horizontalInterval: axis.interval,
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
                        reservedSize: 50,
                        interval: axis.interval,
                        getTitlesWidget: (value, meta) => FittedBox(
                          // Scale down rather than wrap into two lines.
                          fit: BoxFit.scaleDown,
                          child: Text(
                            formatChartAxisValue(value, step: axis.interval),
                            maxLines: 1,
                            softWrap: false,
                            style: Theme.of(context).textTheme.labelSmall,
                          ),
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
                          // Cap at ~6 labels so they never overlap.
                          if (index % labelEvery != 0) {
                            return const SizedBox.shrink();
                          }
                          return Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              formatPeriodShort(months[index].month),
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
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Text(
                'Tap a bar to inspect that ${periodNoun(report.granularity)}. '
                'Average over the completed ones: '
                '${formatCurrency(report.averageExpenses, report.baseCurrency)}.',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Stack segments for one period, in report category order. The period being
  /// inspected keeps its full color; the rest is context.
  List<BarChartRodStackItem> _stackFor(SpendingMonth month) {
    final dim = month.month != selectedPeriod;
    final items = <BarChartRodStackItem>[];
    var from = 0.0;
    for (final category in categories) {
      final value = month.byCategory[category] ?? 0;
      if (value <= 0) continue;
      final color = colorFor(category);
      items.add(BarChartRodStackItem(
        from,
        from + value,
        dim ? color.withValues(alpha: 0.5) : color,
      ));
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

/// One row of the ranking: what a category cost this period, next to what it
/// usually costs and what it was allowed to cost.
typedef _CategoryRow = ({
  String name,
  double amount,
  double? previous,
  double? average,
  double? budget,
});

class _BreakdownCard extends ConsumerWidget {
  final SpendingReport report;
  final SpendingMonth month;
  final SpendingMonth? previous;
  final List<SpendingMonth> trailing;
  final bool showUncategorized;
  final Color Function(String) colorFor;

  const _BreakdownCard({
    required this.report,
    required this.month,
    required this.previous,
    required this.trailing,
    required this.showUncategorized,
    required this.colorFor,
  });

  /// Narrow the transaction list to one category and go there. The period is
  /// already whatever the period bar says, so the list opens on the same
  /// slice of the same category the breakdown was showing.
  void _showTransactions(BuildContext context, WidgetRef ref, String category) {
    final notifier = ref.read(transactionsFilterProvider.notifier);
    if (category == _uncategorizedLabel) {
      // The bucket is an absence of category, not one to filter by.
      notifier.setShow(TransactionsShow.uncategorized);
    } else {
      final id = (ref.read(categoriesProvider).value ?? const [])
          .where((c) => c.name == category)
          .map((c) => c.id)
          .firstOrNull;
      if (id == null) return;
      notifier.setCategories([id]);
    }
    DefaultTabController.of(context).animateTo(1);
  }

  /// Mean of the periods that actually had this category, or null when there
  /// is nothing to average — see [Comparison].
  double? _averageOf(String category) {
    final seen = trailing
        .map((m) => m.byCategory[category] ?? 0)
        .where((v) => v != 0)
        .toList();
    if (seen.isEmpty) return null;
    return seen.fold<double>(0, (sum, v) => sum + v) / seen.length;
  }

  List<_CategoryRow> _rows() {
    // Budgeted categories appear even with nothing spent — "CHF 200 left" is
    // exactly the row a budget is there to show, and dropping it would make a
    // category look untracked.
    final spent = <String, double>{
      ...month.byCategory,
      for (final name in report.budgets.keys)
        if (!month.byCategory.containsKey(name)) name: 0,
    };
    final rows = [
      for (final entry in spent.entries)
        if (showUncategorized || entry.key != _uncategorizedLabel)
          (
            name: entry.key,
            amount: entry.value,
            previous: previous?.byCategory[entry.key],
            average: _averageOf(entry.key),
            budget: report.budgets[entry.key],
          ),
    ]..sort((a, b) => b.amount.compareTo(a.amount));
    return rows;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rows = _rows();
    final total = rows.fold<double>(0, (sum, r) => sum + r.amount);
    final entries = rows.where((r) => r.amount > 0).toList();

    final index = report.months.indexWhere((m) => m.month == month.month);
    final currency = report.baseCurrency;
    final noun = periodNoun(report.granularity);

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
                    'Breakdown · ${formatPeriod(month.month)}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_left),
                  tooltip: 'Previous $noun',
                  onPressed: index > 0
                      ? () => ref
                          .read(spendingSelectedMonthProvider.notifier)
                          .set(report.months[index - 1].month)
                      : null,
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_right),
                  tooltip: 'Next $noun',
                  onPressed: index >= 0 && index < report.months.length - 1
                      ? () => ref
                          .read(spendingSelectedMonthProvider.notifier)
                          .set(report.months[index + 1].month)
                      : null,
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (rows.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 32),
                child: Center(child: Text('No spending in this $noun.')),
              )
            else ...[
              if (entries.isNotEmpty)
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
                            for (final row in entries)
                              PieChartSectionData(
                                value: row.amount,
                                color: colorFor(row.name),
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
                            // Full format with thousands separator — the compact
                            // one rendered mid-size totals as e.g. "CHF 14347".
                            formatCurrency(total, currency),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          Text(
                            formatPeriod(month.month),
                            style: Theme.of(context).textTheme.labelSmall,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 12),
              // Bars are scaled against the largest of spend and budget, so a
              // category under its target shows visibly short of the marker.
              for (final row in rows)
                _CategoryRankingRow(
                  row: row,
                  color: colorFor(row.name),
                  largest: rows.fold<double>(
                      0,
                      (max, r) => [max, r.amount, r.budget ?? 0]
                          .reduce((a, b) => a > b ? a : b)),
                  total: total,
                  currency: currency,
                  onTap: () => CategoryDetailSheet.show(
                    context,
                    category: row.name,
                    color: colorFor(row.name),
                    report: report,
                    selectedPeriod: month.month,
                    onSelectPeriod: (period) => ref
                        .read(spendingSelectedMonthProvider.notifier)
                        .set(period),
                    onShowTransactions: () =>
                        _showTransactions(context, ref, row.name),
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

/// One category of the selected period: its share as a bar, what it cost, how
/// that compares with its own average, and how the budget is holding up.
///
/// A budget shows as a marker on the bar rather than a second bar: the
/// question is how close the spend is to the line, which two bars make you
/// measure by eye.
class _CategoryRankingRow extends StatelessWidget {
  final _CategoryRow row;
  final Color color;
  final double largest;
  final double total;
  final String currency;
  final VoidCallback onTap;

  const _CategoryRankingRow({
    required this.row,
    required this.color,
    required this.largest,
    required this.total,
    required this.currency,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.labelSmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final budget = row.budget;
    final over = budget != null && row.amount > budget;
    // The average is the better yardstick; the previous period stands in only
    // while there is no history to average.
    final reference = row.average ?? row.previous;

    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: color,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    row.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodyMedium,
                  ),
                ),
                Text(formatCurrency(row.amount, currency),
                    style: theme.textTheme.bodyMedium),
                const SizedBox(width: 10),
                SizedBox(
                  width: 38,
                  child: Text(
                    total > 0
                        ? '${(row.amount / total * 100).round()}%'
                        : '0%',
                    textAlign: TextAlign.right,
                    style: muted,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            SizedBox(
              height: 6,
              child: Stack(
                children: [
                  Container(
                    decoration: BoxDecoration(
                      color: theme.dividerColor.withValues(alpha: 0.4),
                      borderRadius: BorderRadius.circular(3),
                    ),
                  ),
                  FractionallySizedBox(
                    widthFactor: largest > 0
                        ? (row.amount / largest).clamp(0.0, 1.0)
                        : 0.0,
                    child: Container(
                      decoration: BoxDecoration(
                        color: color,
                        borderRadius: BorderRadius.circular(3),
                        border: over
                            ? Border.all(color: theme.colorScheme.error)
                            : null,
                      ),
                    ),
                  ),
                  if (budget != null && budget > 0 && largest > 0)
                    Align(
                      // Alignment runs -1..1 across the track.
                      alignment: Alignment(
                        ((budget / largest).clamp(0.0, 1.0) * 2 - 1)
                            .toDouble(),
                        0,
                      ),
                      child: Container(
                        width: 2,
                        color: theme.colorScheme.onSurface,
                      ),
                    ),
                ],
              ),
            ),
            if (reference != null || budget != null) ...[
              const SizedBox(height: 4),
              Row(
                children: [
                  const SizedBox(width: 18),
                  if (reference != null && reference != 0)
                    Expanded(
                      child: _Delta(
                        change: (row.amount - reference) / reference.abs(),
                        moreIsBetter: false,
                        suffix: row.average != null ? 'vs avg' : 'vs last',
                      ),
                    ),
                  if (budget != null)
                    Expanded(
                      child: Text(
                        over
                            ? '${formatCurrency(row.amount - budget, currency)} over budget'
                            : '${formatCurrency(budget - row.amount, currency)} left of budget',
                        textAlign: TextAlign.right,
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: over
                              ? theme.colorScheme.error
                              : theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
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
