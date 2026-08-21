import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/chart_axis.dart';
import '../../core/utils/formatters.dart';
import '../../data/models/simulation.dart';
import '../providers/wealth_provider.dart';

const _yearOptions = [5, 10, 15, 20, 30];
const _targetColor = Color(0xFFF87171);

/// Monte Carlo wealth projection: percentile fan chart plus editable
/// assumptions, shown in today's purchasing power.
///
/// Persistence contract: each run sends ONLY the parameters the user changed —
/// the server stores those as profile overrides (shared with the web app) and
/// keeps deriving the untouched ones fresh. Clearing a field sends an empty
/// value, which removes the stored override.
///
/// The server always simulates the full 30-year horizon, so switching the
/// horizon chips only re-slices the cached bands locally (instant) and
/// persists the choice in the background.
class SimulationScreen extends ConsumerStatefulWidget {
  const SimulationScreen({super.key});

  @override
  ConsumerState<SimulationScreen> createState() => _SimulationScreenState();
}

class _SimulationScreenState extends ConsumerState<SimulationScreen> {
  SimulationResult? _result;
  String? _error;
  bool _busy = false;
  // Horizon picked via the chips this session; null = whatever the server
  // resolved (stored override or default).
  int? _displayYears;

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

  /// Chip tap: re-slice the already-loaded bands (instant) and persist the
  /// horizon in the background — the response is ignored, a minimal `paths`
  /// keeps that request cheap.
  void _selectYears(int years) {
    setState(() => _displayYears = years);
    ref
        .read(wealthRepositoryProvider)
        .getSimulation(params: {'years': '$years', 'paths': '100'})
        .ignore();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final result = _result;
    final years = _displayYears ?? result?.years ?? 15;

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
                    selected: years == y,
                    onSelected: (_) => _selectYears(y),
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
                  padding: const EdgeInsets.fromLTRB(8, 12, 16, 8),
                  child: _FanChart(
                    // Re-slicing must reset the sticky selection: a marked
                    // year can lie outside the new horizon.
                    key: ValueKey('$years-${identityHashCode(result)}'),
                    result: result,
                    displayYears: years,
                  ),
                ),
              ),
              if (result.target != null)
                _TargetSummary(result: result, displayYears: years),
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

/// Percentile fan with the same sticky touch model as the dashboard chart:
/// values render in a fixed row above the chart (never clipped), sliding
/// updates them live, and lifting the finger or tapping keeps the last year
/// selected.
class _FanChart extends StatefulWidget {
  final SimulationResult result;
  final int displayYears;

  const _FanChart({super.key, required this.result, required this.displayYears});

  @override
  State<_FanChart> createState() => _FanChartState();
}

class _FanChartState extends State<_FanChart> {
  int? _markedYear;
  int? _lastTouchedYear;

  List<SimulationBand> get _bands {
    final bands = widget.result.bands;
    final end = (widget.displayYears + 1).clamp(0, bands.length);
    return bands.sublist(0, end);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final primary = theme.colorScheme.primary;
    final bands = _bands;
    final target = widget.result.target;

    List<FlSpot> spots(double Function(SimulationBand) pick) => [
          for (final band in bands) FlSpot(band.year.toDouble(), pick(band)),
        ];

    LineChartBarData invisible(List<FlSpot> data) => LineChartBarData(
          spots: data,
          color: Colors.transparent,
          dotData: const FlDotData(show: false),
        );

    var maxValue = bands.map((b) => b.p95).reduce((a, b) => a > b ? a : b);
    // Keep the target line in view — unless it would squash the fan.
    final showTargetLine =
        target != null && target.amount <= maxValue * 2 && target.amount > 0;
    if (showTargetLine && target.amount > maxValue) {
      maxValue = target.amount;
    }
    final axis = niceAxis(0, maxValue * 1.05);

    final displayYear = _lastTouchedYear ?? _markedYear;
    final displayBand = displayYear != null && displayYear < bands.length
        ? bands[displayYear]
        : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Fixed-position value display (like the dashboard chart) — cannot be
        // clipped at the chart edges the way a floating tooltip is. FittedBox
        // scales the text down rather than letting it wrap into a second line
        // that would collide with the topmost y-axis label.
        Container(
          height: 32,
          width: double.infinity,
          alignment: Alignment.center,
          child: displayBand != null
              ? FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    '+${displayBand.year}y   '
                    'Median ${formatChartAxisValue(displayBand.p50)} · '
                    '75% ${formatChartAxisValue(displayBand.p75)} · '
                    '95% ${formatChartAxisValue(displayBand.p95)}',
                    maxLines: 1,
                    softWrap: false,
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                )
              : Text(
                  'Slide on chart to see values',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
        ),
        // Clear separation from the topmost y-axis label.
        const SizedBox(height: 12),
        SizedBox(
          height: 240,
          child: LineChart(
            LineChartData(
              minY: axis.min,
              maxY: axis.max,
              lineTouchData: LineTouchData(
                handleBuiltInTouches: true,
                touchCallback: (event, response) {
                  final touchedYear =
                      response?.lineBarSpots?.firstOrNull?.x.toInt();

                  if (event is FlTapUpEvent) {
                    if (touchedYear != null) {
                      setState(() {
                        _markedYear = touchedYear;
                        _lastTouchedYear = null;
                      });
                    }
                    return;
                  }
                  if (event is FlPointerExitEvent ||
                      event is FlPanEndEvent ||
                      event is FlLongPressEnd) {
                    if (_lastTouchedYear != null) {
                      setState(() {
                        _markedYear = _lastTouchedYear;
                        _lastTouchedYear = null;
                      });
                    }
                    return;
                  }
                  if (touchedYear != null && touchedYear != _lastTouchedYear) {
                    setState(() => _lastTouchedYear = touchedYear);
                  }
                },
                // No floating tooltip — values live in the fixed row above.
                touchTooltipData: LineTouchTooltipData(
                  getTooltipItems: (spots) => spots.map((_) => null).toList(),
                ),
                getTouchedSpotIndicator: (barData, spotIndexes) =>
                    spotIndexes.map((index) {
                  // Indicator only on the median line; the invisible band
                  // edges would each paint their own dot otherwise.
                  if (barData.color == Colors.transparent) {
                    return const TouchedSpotIndicatorData(
                      FlLine(color: Colors.transparent, strokeWidth: 0),
                      FlDotData(show: false),
                    );
                  }
                  return TouchedSpotIndicatorData(
                    FlLine(
                      color: primary,
                      strokeWidth: 1,
                      dashArray: [4, 4],
                    ),
                    FlDotData(
                      show: true,
                      getDotPainter: (spot, percent, bar, idx) =>
                          FlDotCirclePainter(
                        radius: 5,
                        color: primary,
                        strokeWidth: 2,
                        strokeColor: theme.colorScheme.surface,
                      ),
                    ),
                  );
                }).toList(),
              ),
              titlesData: FlTitlesData(
                topTitles:
                    const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles:
                    const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    interval: (widget.displayYears / 5).ceilToDouble(),
                    getTitlesWidget: (value, meta) => SideTitleWidget(
                      meta: meta,
                      child: Text(
                        '+${value.toInt()}y',
                        style: theme.textTheme.labelSmall,
                      ),
                    ),
                  ),
                ),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 48,
                    interval: axis.interval,
                    getTitlesWidget: (value, meta) => SideTitleWidget(
                      meta: meta,
                      child: Text(
                        formatChartAxisValue(value, step: axis.interval),
                        style: theme.textTheme.labelSmall,
                      ),
                    ),
                  ),
                ),
              ),
              gridData: FlGridData(
                drawVerticalLine: false,
                horizontalInterval: axis.interval,
                getDrawingHorizontalLine: (_) => FlLine(
                  color: theme.dividerColor.withValues(alpha: 0.4),
                  strokeWidth: 1,
                ),
              ),
              borderData: FlBorderData(show: false),
              // Bar order matters: fills go between indexed bars; the median
              // (index 4) is the only visible line.
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
              extraLinesData: ExtraLinesData(
                horizontalLines: [
                  if (showTargetLine)
                    HorizontalLine(
                      y: target.amount,
                      color: _targetColor,
                      strokeWidth: 1.5,
                      dashArray: [6, 4],
                    ),
                ],
                verticalLines: [
                  // Where the median path crosses the target.
                  if (target?.medianReachedYear != null &&
                      target!.medianReachedYear! <= widget.displayYears)
                    VerticalLine(
                      x: target.medianReachedYear!.toDouble(),
                      color: _targetColor,
                      strokeWidth: 1,
                      dashArray: [4, 4],
                    ),
                  // Sticky selection marker (when not actively touching).
                  if (_markedYear != null && _lastTouchedYear == null)
                    VerticalLine(
                      x: _markedYear!.toDouble(),
                      color: primary,
                      strokeWidth: 1,
                      dashArray: [4, 4],
                    ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _TargetSummary extends StatelessWidget {
  final SimulationResult result;
  final int displayYears;

  const _TargetSummary({required this.result, required this.displayYears});

  @override
  Widget build(BuildContext context) {
    final target = result.target!;
    final theme = Theme.of(context);
    // Per-year probabilities let the horizon chips re-slice without a request.
    final byYear = target.probabilityByYear;
    final probability = displayYears < byYear.length
        ? byYear[displayYears]
        : target.probability;
    final pct = (probability * 100).toStringAsFixed(0);
    final reached = target.medianReachedYear;
    final medianText = reached != null && reached <= displayYears
        ? 'The median path gets there in year $reached (red line).'
        : 'The median path does not get there in this horizon.';

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Text(
        'Probability of reaching '
        '${formatCurrency(target.amount, result.baseCurrency)} within '
        '$displayYears years: $pct%. $medianText',
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

  // (key, label, isPercent, hint): percent parameters are edited as "5.2",
  // sent as 0.052.
  static const _fields = [
    (
      'start_wealth',
      'Starting wealth',
      false,
      'Your total wealth today. Derived from the latest account balances.',
    ),
    (
      'monthly_contribution',
      'Monthly contribution',
      false,
      'What you save per month (income minus spending). Negative means '
          'drawing down.',
    ),
    (
      'expected_return',
      'Expected return (%/y)',
      true,
      'Average yearly investment growth before inflation.',
    ),
    (
      'volatility',
      'Volatility (%/y)',
      true,
      'How much returns swing from year to year. Higher makes the outcome '
          'bands wider.',
    ),
    (
      'inflation',
      'Inflation (%/y)',
      true,
      'Yearly loss of purchasing power; subtracted from the return.',
    ),
  ];

  @override
  void initState() {
    super.initState();
    _prefill = {
      for (final (key, _, isPercent, _) in _fields)
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
    for (final (key, _, isPercent, _) in _fields) {
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
            for (final (key, label, _, hint) in _fields)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: TextField(
                  controller: _controllers[key],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                    signed: true,
                  ),
                  decoration: InputDecoration(
                    labelText: label,
                    helperText: hint,
                    helperMaxLines: 3,
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
                helperText:
                    'A goal to aim for — shows the probability of reaching it '
                    'and marks it red in the chart.',
                helperMaxLines: 3,
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
