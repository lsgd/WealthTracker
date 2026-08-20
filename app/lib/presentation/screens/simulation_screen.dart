import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../../data/models/simulation.dart';
import '../providers/wealth_provider.dart';

const _yearOptions = [5, 10, 15, 20, 30];

/// Monte Carlo wealth projection: percentile fan chart plus editable
/// assumptions, shown in today's purchasing power.
///
/// Persistence contract: each run sends ONLY the parameters the user changed —
/// the server stores those as profile overrides (shared with the web app) and
/// keeps deriving the untouched ones fresh. Clearing a field sends an empty
/// value, which removes the stored override.
class SimulationScreen extends ConsumerStatefulWidget {
  const SimulationScreen({super.key});

  @override
  ConsumerState<SimulationScreen> createState() => _SimulationScreenState();
}

class _SimulationScreenState extends ConsumerState<SimulationScreen> {
  SimulationResult? _result;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    // No parameters: stored overrides + fresh derivation apply.
    _run();
  }

  Future<void> _run([Map<String, String> params = const {}]) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await ref
          .read(wealthRepositoryProvider)
          .getSimulation(params: params);
      if (mounted) setState(() => _result = result);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final result = _result;

    return Scaffold(
      appBar: AppBar(title: const Text('Simulation')),
      body: RefreshIndicator(
        onRefresh: _run,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Wrap(
              spacing: 6,
              children: [
                for (final y in _yearOptions)
                  ChoiceChip(
                    label: Text('${y}y'),
                    selected: (result?.years ?? 15) == y,
                    onSelected: (_) => _run({'years': '$y'}),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Monte Carlo projection in today\'s purchasing power. Bands are '
              'the 5–95% and 25–75% ranges, the line is the median. Changed '
              'assumptions are saved to your profile.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            if (_error != null)
              Card(
                color: theme.colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    _error!,
                    style:
                        TextStyle(color: theme.colorScheme.onErrorContainer),
                  ),
                ),
              )
            else if (result == null)
              const SizedBox(
                height: 280,
                child: Center(child: CircularProgressIndicator()),
              )
            else ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(8, 24, 16, 8),
                  child: SizedBox(
                    height: 260,
                    child: _FanChart(result: result),
                  ),
                ),
              ),
              if (result.target != null) _TargetSummary(result: result),
              const SizedBox(height: 8),
              // Keyed to the result: after every run the card re-prefills from
              // the fresh echo, which is also the baseline for change
              // detection on the next Apply.
              _AssumptionsCard(
                key: ObjectKey(result),
                result: result,
                busy: _busy,
                onApply: _run,
              ),
            ],
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }
}

class _FanChart extends StatelessWidget {
  final SimulationResult result;
  const _FanChart({required this.result});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final primary = theme.colorScheme.primary;

    List<FlSpot> spots(double Function(SimulationBand) pick) => [
          for (final band in result.bands)
            FlSpot(band.year.toDouble(), pick(band)),
        ];

    LineChartBarData invisible(List<FlSpot> data) => LineChartBarData(
          spots: data,
          color: Colors.transparent,
          dotData: const FlDotData(show: false),
        );

    final maxY = result.bands.map((b) => b.p95).reduce((a, b) => a > b ? a : b);

    return LineChart(
      LineChartData(
        minY: 0,
        maxY: maxY * 1.05,
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipItems: (touched) => [
              for (final spot in touched)
                // Only label the median line; the band edges are context.
                if (spot.barIndex == 4)
                  LineTooltipItem(
                    'Year +${spot.x.toInt()}\n'
                    '${formatCurrencyCompact(spot.y, result.baseCurrency)}',
                    TextStyle(
                      color: theme.colorScheme.onInverseSurface,
                      fontWeight: FontWeight.w600,
                    ),
                  )
                else
                  null,
            ],
          ),
        ),
        titlesData: FlTitlesData(
          topTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles:
              const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              interval: (result.years / 5).ceilToDouble(),
              getTitlesWidget: (value, meta) => SideTitleWidget(
                meta: meta,
                child: Text(
                  '+${value.toInt()}y',
                  style: theme.textTheme.bodySmall,
                ),
              ),
            ),
          ),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 56,
              getTitlesWidget: (value, meta) => SideTitleWidget(
                meta: meta,
                child: Text(
                  formatCurrencyCompact(value, result.baseCurrency),
                  style: theme.textTheme.bodySmall,
                ),
              ),
            ),
          ),
        ),
        gridData: FlGridData(
          drawVerticalLine: false,
          getDrawingHorizontalLine: (_) => FlLine(
            color: theme.dividerColor.withValues(alpha: 0.4),
            strokeWidth: 1,
          ),
        ),
        borderData: FlBorderData(show: false),
        // Bar order matters: fills go between indexed bars, tooltip keys off
        // index 4 (the median).
        lineBarsData: [
          invisible(spots((b) => b.p5)), // 0
          invisible(spots((b) => b.p95)), // 1
          invisible(spots((b) => b.p25)), // 2
          invisible(spots((b) => b.p75)), // 3
          LineChartBarData(
            spots: spots((b) => b.p50), // 4
            color: primary,
            barWidth: 2.5,
            dotData: const FlDotData(show: false),
          ),
        ],
        betweenBarsData: [
          BetweenBarsData(
            fromIndex: 0,
            toIndex: 1,
            color: primary.withValues(alpha: 0.10),
          ),
          BetweenBarsData(
            fromIndex: 2,
            toIndex: 3,
            color: primary.withValues(alpha: 0.20),
          ),
        ],
      ),
    );
  }
}

class _TargetSummary extends StatelessWidget {
  final SimulationResult result;
  const _TargetSummary({required this.result});

  @override
  Widget build(BuildContext context) {
    final target = result.target!;
    final theme = Theme.of(context);
    final pct = (target.probability * 100).toStringAsFixed(0);
    final medianText = target.medianReachedYear != null
        ? 'The median path gets there in year ${target.medianReachedYear}.'
        : 'The median path does not get there in this horizon.';

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Text(
        'Probability of reaching '
        '${formatCurrency(target.amount, result.baseCurrency)} within '
        '${result.years} years: $pct%. $medianText',
        style: theme.textTheme.bodySmall,
      ),
    );
  }
}

class _AssumptionsCard extends StatefulWidget {
  final SimulationResult result;
  final bool busy;
  final void Function(Map<String, String> changed) onApply;

  const _AssumptionsCard({
    super.key,
    required this.result,
    required this.busy,
    required this.onApply,
  });

  @override
  State<_AssumptionsCard> createState() => _AssumptionsCardState();
}

class _AssumptionsCardState extends State<_AssumptionsCard> {
  late final Map<String, TextEditingController> _controllers;
  late final TextEditingController _targetController;
  // Text as prefilled from the echo — the baseline for "did the user change it".
  late final Map<String, String> _prefill;
  late final String _targetPrefill;

  // (key, label, isPercent): percent parameters are edited as "5.2", sent as 0.052.
  static const _fields = [
    ('start_wealth', 'Starting wealth', false),
    ('monthly_contribution', 'Monthly contribution', false),
    ('expected_return', 'Expected return (%/y)', true),
    ('volatility', 'Volatility (%/y)', true),
    ('inflation', 'Inflation (%/y)', true),
  ];

  @override
  void initState() {
    super.initState();
    _prefill = {
      for (final (key, _, isPercent) in _fields)
        key: _echoText(key, isPercent),
    };
    _controllers = {
      for (final entry in _prefill.entries)
        entry.key: TextEditingController(text: entry.value),
    };
    _targetPrefill =
        widget.result.target?.amount.toStringAsFixed(0) ?? '';
    _targetController = TextEditingController(text: _targetPrefill);
  }

  String _echoText(String key, bool isPercent) {
    final parameter = widget.result.parameters[key];
    if (parameter == null) return '';
    return isPercent
        ? (parameter.value * 100).toStringAsFixed(1)
        : parameter.value.round().toString();
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    _targetController.dispose();
    super.dispose();
  }

  void _apply() {
    final changed = <String, String>{};
    for (final (key, _, isPercent) in _fields) {
      final text = _controllers[key]!.text.trim().replaceAll(',', '.');
      if (text == _prefill[key]) continue;
      if (text.isEmpty) {
        changed[key] = ''; // clear the stored override
        continue;
      }
      final value = double.tryParse(text);
      if (value == null) continue;
      changed[key] = isPercent ? '${value / 100}' : text;
    }
    final targetText = _targetController.text.trim().replaceAll(',', '.');
    if (targetText != _targetPrefill) {
      changed['target_amount'] = targetText;
    }
    widget.onApply(changed);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Assumptions', style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              'Defaults are derived from your accounts, spending, and '
              'holdings. Changes are saved; clear a field to go back to the '
              'derived value.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            for (final (key, label, _) in _fields)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: TextField(
                  controller: _controllers[key],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                    signed: true,
                  ),
                  decoration: InputDecoration(
                    labelText: label,
                    suffixText: widget.result.parameters[key]?.derived == true
                        ? 'derived'
                        : null,
                    isDense: true,
                    border: const OutlineInputBorder(),
                  ),
                ),
              ),
            TextField(
              controller: _targetController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Target amount (optional)',
                isDense: true,
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton.icon(
                onPressed: widget.busy ? null : _apply,
                icon: widget.busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.play_arrow, size: 18),
                label: const Text('Run simulation'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
