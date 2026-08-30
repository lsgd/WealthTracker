import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/transactions.dart';
import '../providers/spending_provider.dart';

/// Open the rule editor for [rule] (or a new rule) and refresh what a saved
/// rule changes: rules apply retroactively, so the transaction list and the
/// report move with them.
Future<void> editRule(
  BuildContext context,
  WidgetRef ref, {
  CategoryRule? rule,
  String? initialMatchText,
  int? initialCategoryId,
  bool initialIsTransfer = false,
}) async {
  final categories = await ref.read(categoriesProvider.future);
  if (!context.mounted) return;
  final saved = await RuleDialog.show(
    context,
    categories: categories,
    rule: rule,
    initialMatchText: initialMatchText,
    initialCategoryId: initialCategoryId,
    initialIsTransfer: initialIsTransfer,
  );
  if (saved == true) {
    ref.invalidate(categoryRulesProvider);
    ref.invalidate(categoriesProvider);
    ref.invalidate(transactionsProvider);
    ref.invalidate(spendingReportProvider);
  }
}

/// Create or edit a categorization rule.
///
/// Everything the rule model can express lives here — the match text, what it
/// targets, and the conditions that narrow it — but the conditions sit behind
/// "Advanced": most rules are a merchant name and a category, and the amount
/// bounds would otherwise be four controls in the way of the two that matter.
///
/// Pops `true` when something was saved.
class RuleDialog extends ConsumerStatefulWidget {
  final List<TransactionCategory> categories;

  /// The rule being edited, or null to create one.
  final CategoryRule? rule;

  /// Prefills for a new rule, e.g. the counterparty and category of the
  /// transaction it was opened from.
  final String? initialMatchText;
  final int? initialCategoryId;
  final bool initialIsTransfer;

  const RuleDialog({
    super.key,
    required this.categories,
    this.rule,
    this.initialMatchText,
    this.initialCategoryId,
    this.initialIsTransfer = false,
  });

  static Future<bool?> show(
    BuildContext context, {
    required List<TransactionCategory> categories,
    CategoryRule? rule,
    String? initialMatchText,
    int? initialCategoryId,
    bool initialIsTransfer = false,
  }) {
    return showDialog<bool>(
      context: context,
      builder: (_) => RuleDialog(
        categories: categories,
        rule: rule,
        initialMatchText: initialMatchText,
        initialCategoryId: initialCategoryId,
        initialIsTransfer: initialIsTransfer,
      ),
    );
  }

  @override
  ConsumerState<RuleDialog> createState() => _RuleDialogState();
}

/// Sentinel for the transfer target in the one dropdown that picks it: a rule
/// assigns a category or marks a transfer, never both.
const _transferTarget = 'transfer';
const _newCategoryTarget = 'new';

class _RuleDialogState extends ConsumerState<RuleDialog> {
  late final TextEditingController _matchController;
  final _newCategoryController = TextEditingController();
  late final TextEditingController _minController;
  late final TextEditingController _maxController;

  int? _categoryId;
  bool _newCategory = false;
  bool _isTransfer = false;
  int _spread = 1;
  bool _isRegex = false;
  String _direction = 'any';
  bool _minInclusive = true;
  bool _maxInclusive = false;
  bool _advancedOpen = false;

  bool _saving = false;
  String? _error;

  Timer? _previewTimer;
  RulePreview? _preview;
  String? _previewError;
  bool _previewLoading = false;

  /// Identifies the input a preview was requested for, so a late answer to an
  /// older question is never shown next to newer input.
  String _previewKey = '';

  @override
  void initState() {
    super.initState();
    final rule = widget.rule;
    _matchController = TextEditingController(
        text: rule?.matchText ?? widget.initialMatchText ?? '');
    _minController = TextEditingController(text: _trim(rule?.minAmount));
    _maxController = TextEditingController(text: _trim(rule?.maxAmount));
    if (rule != null) {
      _categoryId = rule.category;
      _isTransfer = rule.isTransfer;
      _spread = rule.spreadMonths;
      _isRegex = rule.isRegex;
      _direction = rule.direction;
      _minInclusive = rule.minInclusive;
      _maxInclusive = rule.maxInclusive;
      // Opened folded away, unless this rule has something in there to show.
      _advancedOpen = rule.amountCondition != null || rule.isRegex;
    } else {
      _categoryId = widget.initialCategoryId;
      _isTransfer = widget.initialIsTransfer;
    }
    _matchController.addListener(_schedulePreview);
    _schedulePreview();
  }

  /// The API renders decimals as "20.00"; trailing zeros in a field the user
  /// is about to edit are noise.
  static String _trim(String? value) {
    if (value == null) return '';
    final number = double.tryParse(value);
    if (number == null) return value;
    return number == number.roundToDouble()
        ? number.toStringAsFixed(0)
        : number.toString();
  }

  @override
  void dispose() {
    _previewTimer?.cancel();
    _matchController.dispose();
    _newCategoryController.dispose();
    _minController.dispose();
    _maxController.dispose();
    super.dispose();
  }

  String? get _minAmount =>
      _minController.text.trim().isEmpty ? null : _minController.text.trim();

  String? get _maxAmount =>
      _maxController.text.trim().isEmpty ? null : _maxController.text.trim();

  /// True when the two bounds exclude every possible amount.
  bool get _impossibleRange {
    final low = double.tryParse(_minAmount ?? '');
    final high = double.tryParse(_maxAmount ?? '');
    if (low == null || high == null) return false;
    // Equal bounds only hold when BOTH ends include the value.
    return low > high || (low == high && !(_minInclusive && _maxInclusive));
  }

  // -- preview ---------------------------------------------------------------

  /// Long enough that typing a merchant name is one request, short enough that
  /// the answer arrives before the eye leaves the field.
  static const _debounce = Duration(milliseconds: 350);

  void _schedulePreview() {
    _previewTimer?.cancel();
    final text = _matchController.text.trim();
    final key = [
      text,
      _isRegex,
      _isTransfer,
      _direction,
      _minAmount,
      _minInclusive,
      _maxAmount,
      _maxInclusive,
    ].join('|');
    if (key == _previewKey) return;
    _previewKey = key;
    if (text.isEmpty || _impossibleRange) {
      setState(() {
        _preview = null;
        _previewError = null;
        _previewLoading = false;
      });
      return;
    }
    setState(() => _previewLoading = true);
    _previewTimer = Timer(_debounce, () => _loadPreview(key));
  }

  Future<void> _loadPreview(String key) async {
    try {
      final preview = await ref.read(spendingRepositoryProvider).previewRule(
            matchText: _matchController.text.trim(),
            isRegex: _isRegex,
            isTransfer: _isTransfer,
            ruleId: widget.rule?.id,
            direction: _direction,
            minAmount: _minAmount,
            minInclusive: _minInclusive,
            maxAmount: _maxAmount,
            maxInclusive: _maxInclusive,
          );
      if (!mounted || key != _previewKey) return;
      setState(() {
        _preview = preview;
        _previewError = null;
        _previewLoading = false;
      });
    } catch (e) {
      if (!mounted || key != _previewKey) return;
      setState(() {
        _preview = null;
        _previewError = '$e';
        _previewLoading = false;
      });
    }
  }

  // -- build -----------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final editing = widget.rule != null;

    return AlertDialog(
      title: Text(editing ? 'Edit rule' : 'New rule'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _matchController,
              autofocus: !editing,
              decoration: InputDecoration(
                labelText: 'Match text',
                hintText: _isRegex ? r'e.g. ^(rewe|edeka)' : 'e.g. rewe',
                helperText: _isRegex
                    ? 'Regular expression, matched against the booking text'
                    : 'Matched anywhere in the booking text, ignoring case',
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<Object?>(
              initialValue: _newCategory
                  ? _newCategoryTarget
                  : (_isTransfer ? _transferTarget : _categoryId),
              decoration: const InputDecoration(labelText: 'Target'),
              items: [
                for (final c in widget.categories)
                  DropdownMenuItem(value: c.id, child: Text(c.name)),
                const DropdownMenuItem(
                  value: _transferTarget,
                  child: Text('Transfer (excluded)'),
                ),
                const DropdownMenuItem(
                  value: _newCategoryTarget,
                  child: Text('New category…'),
                ),
              ],
              onChanged: (value) => setState(() {
                _newCategory = value == _newCategoryTarget;
                _isTransfer = value == _transferTarget;
                _categoryId = value is int ? value : null;
                _schedulePreview();
              }),
            ),
            if (_newCategory) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _newCategoryController,
                decoration:
                    const InputDecoration(labelText: 'New category name'),
              ),
            ],
            // A transfer is excluded from spending — nothing to amortize.
            if (!_isTransfer) ...[
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: const [1, 3, 6, 12].contains(_spread)
                    ? _spread
                    : null,
                decoration: const InputDecoration(
                  labelText: 'Spread',
                  helperText: 'Amortize a yearly bill across months',
                ),
                items: const [
                  DropdownMenuItem(value: 1, child: Text('No spread')),
                  DropdownMenuItem(value: 3, child: Text('3 months')),
                  DropdownMenuItem(value: 6, child: Text('6 months')),
                  DropdownMenuItem(value: 12, child: Text('12 months')),
                ],
                onChanged: (value) => setState(() => _spread = value ?? 1),
              ),
            ],
            const SizedBox(height: 4),
            _AdvancedSection(
              open: _advancedOpen,
              summary: _conditionSummary,
              onToggle: (open) => setState(() => _advancedOpen = open),
              children: [
                SwitchListTile(
                  title: const Text('Regular expression'),
                  subtitle: const Text('Match with a regex instead of plain text'),
                  contentPadding: EdgeInsets.zero,
                  value: _isRegex,
                  onChanged: (value) => setState(() {
                    _isRegex = value;
                    _schedulePreview();
                  }),
                ),
                const SizedBox(height: 4),
                SegmentedButton<String>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: 'any', label: Text('Any')),
                    ButtonSegment(value: 'payment', label: Text('Payments')),
                    ButtonSegment(value: 'income', label: Text('Income')),
                  ],
                  selected: {_direction},
                  onSelectionChanged: (values) => setState(() {
                    _direction = values.first;
                    _schedulePreview();
                  }),
                ),
                const SizedBox(height: 8),
                // Bounds are compared without a sign — direction above carries
                // it — so they are spoken about as sizes and stay positive.
                _Bound(
                  controller: _minController,
                  label: 'At least',
                  inclusive: _minInclusive,
                  inclusiveLabel: 'Including the bound (≥)',
                  onInclusive: (value) => setState(() {
                    _minInclusive = value;
                    _schedulePreview();
                  }),
                  onChanged: _schedulePreview,
                ),
                _Bound(
                  controller: _maxController,
                  label: 'At most',
                  inclusive: _maxInclusive,
                  inclusiveLabel: 'Including the bound (≤)',
                  onInclusive: (value) => setState(() {
                    _maxInclusive = value;
                    _schedulePreview();
                  }),
                  onChanged: _schedulePreview,
                ),
              ],
            ),
            const SizedBox(height: 8),
            _Impact(
              matchText: _matchController.text.trim(),
              impossibleRange: _impossibleRange,
              loading: _previewLoading,
              preview: _preview,
              error: _previewError,
              isTransfer: _isTransfer,
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.pop(context, false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _saving ? null : _save,
          child: Text(_saving ? 'Saving…' : (editing ? 'Save' : 'Create')),
        ),
      ],
    );
  }

  String? get _conditionSummary {
    final parts = [
      if (_isRegex) 'regex',
      if (_direction == 'payment') 'payments',
      if (_direction == 'income') 'income',
      if (_minAmount != null) '${_minInclusive ? '≥' : '>'} ${_minAmount!}',
      if (_maxAmount != null) '${_maxInclusive ? '≤' : '<'} ${_maxAmount!}',
    ];
    return parts.isEmpty ? null : parts.join(', ');
  }

  Future<void> _save() async {
    final matchText = _matchController.text.trim();
    if (matchText.isEmpty) {
      setState(() => _error = 'Enter the text to match.');
      return;
    }
    if (_impossibleRange) {
      setState(() => _error = 'No amount can satisfy both bounds.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final repository = ref.read(spendingRepositoryProvider);
      var categoryId = _categoryId;
      if (!_isTransfer) {
        if (_newCategory) {
          final name = _newCategoryController.text.trim();
          if (name.isEmpty) {
            setState(() {
              _saving = false;
              _error = 'Enter a name for the new category.';
            });
            return;
          }
          categoryId = (await repository.createCategory(name)).id;
        }
        if (categoryId == null) {
          setState(() {
            _saving = false;
            _error = 'Pick a category, or make this a transfer rule.';
          });
          return;
        }
      }
      final rule = widget.rule;
      if (rule == null) {
        await repository.createRule(
          matchText: matchText,
          categoryId: categoryId,
          isTransfer: _isTransfer,
          spreadMonths: _spread,
          isRegex: _isRegex,
          direction: _direction,
          minAmount: _minAmount,
          minInclusive: _minInclusive,
          maxAmount: _maxAmount,
          maxInclusive: _maxInclusive,
        );
      } else {
        await repository.saveRule(
          rule.id,
          matchText: matchText,
          categoryId: categoryId,
          isTransfer: _isTransfer,
          spreadMonths: _spread,
          isRegex: _isRegex,
          direction: _direction,
          minAmount: _minAmount,
          minInclusive: _minInclusive,
          maxAmount: _maxAmount,
          maxInclusive: _maxInclusive,
        );
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() {
        _saving = false;
        _error = '$e';
      });
    }
  }
}

/// The conditions, folded away until they are wanted — with a summary so a
/// rule that has them never looks like a plain one.
class _AdvancedSection extends StatelessWidget {
  final bool open;
  final String? summary;
  final ValueChanged<bool> onToggle;
  final List<Widget> children;

  const _AdvancedSection({
    required this.open,
    required this.summary,
    required this.onToggle,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => onToggle(!open),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(
              children: [
                Icon(open ? Icons.expand_less : Icons.expand_more, size: 20),
                const SizedBox(width: 4),
                Text('Advanced', style: theme.textTheme.labelLarge),
                if (!open && summary != null) ...[
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      summary!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        if (open) ...children,
      ],
    );
  }
}

class _Bound extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final bool inclusive;
  final String inclusiveLabel;
  final ValueChanged<bool> onInclusive;
  final VoidCallback onChanged;

  const _Bound({
    required this.controller,
    required this.label,
    required this.inclusive,
    required this.inclusiveLabel,
    required this.onInclusive,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TextField(
          controller: controller,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          inputFormatters: [
            FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
          ],
          decoration: InputDecoration(
            labelText: label,
            hintText: 'any amount',
            isDense: true,
          ),
          onChanged: (_) => onChanged(),
        ),
        SwitchListTile(
          title: Text(inclusiveLabel),
          dense: true,
          contentPadding: EdgeInsets.zero,
          value: inclusive,
          onChanged: onInclusive,
        ),
      ],
    );
  }
}

/// What the rule would do to the transactions already imported.
class _Impact extends StatelessWidget {
  final String matchText;
  final bool impossibleRange;
  final bool loading;
  final RulePreview? preview;
  final String? error;
  final bool isTransfer;

  const _Impact({
    required this.matchText,
    required this.impossibleRange,
    required this.loading,
    required this.preview,
    required this.error,
    required this.isTransfer,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall
        ?.copyWith(color: theme.colorScheme.onSurfaceVariant);

    if (matchText.isEmpty) return const SizedBox.shrink();
    if (impossibleRange) {
      return Text(
        'The amount range is empty — no transaction can satisfy both bounds.',
        style: theme.textTheme.bodySmall
            ?.copyWith(color: theme.colorScheme.error),
      );
    }
    if (error != null) {
      return Text(error!,
          style: theme.textTheme.bodySmall
              ?.copyWith(color: theme.colorScheme.error));
    }
    if (preview == null) return Text('Checking…', style: muted);

    final p = preview!;
    final verb = isTransfer ? 'mark as transfers' : 'categorize';
    final notes = [
      if (p.shadowed > 0)
        '${p.shadowed} more ${p.shadowed == 1 ? 'is' : 'are'} claimed by an '
            'earlier rule',
      if (p.alreadyClassified > 0)
        '${p.alreadyClassified} more already '
            '${p.alreadyClassified == 1 ? 'has' : 'have'} a category',
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Opacity(
          // Dimmed rather than replaced: the previous answer stays readable
          // until its replacement lands.
          opacity: loading ? 0.5 : 1,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                p.willClassify > 0
                    ? 'Will $verb ${p.willClassify} existing '
                        '${p.willClassify == 1 ? 'transaction' : 'transactions'}'
                    : (p.matched == 0
                        ? 'Matches nothing so far — it still applies to future '
                            'bookings'
                        : 'No existing transaction would change'),
                style: theme.textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: p.willClassify > 0
                      ? theme.colorScheme.primary
                      : theme.colorScheme.onSurfaceVariant,
                ),
              ),
              if (notes.isNotEmpty) Text('(${notes.join(', ')})', style: muted),
              for (final example in p.examples)
                Text(
                  '· ${example.text}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: muted,
                ),
            ],
          ),
        ),
      ],
    );
  }
}
