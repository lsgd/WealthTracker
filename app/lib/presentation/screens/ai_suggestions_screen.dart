import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../../data/models/ai_categorization.dart';
import '../providers/spending_provider.dart';

/// Review screen for Gemini's proposals.
///
/// Nothing here is stored until the user confirms: every suggestion and rule is
/// individually selectable, and only the ticked ones are sent to the apply
/// endpoint.
class AiSuggestionsScreen extends ConsumerStatefulWidget {
  const AiSuggestionsScreen({super.key});

  @override
  ConsumerState<AiSuggestionsScreen> createState() =>
      _AiSuggestionsScreenState();
}

class _AiSuggestionsScreenState extends ConsumerState<AiSuggestionsScreen> {
  AiSuggestResponse? _result;
  final _acceptedTx = <int>{};
  final _acceptedRules = <int>{};
  final _scrollController = ScrollController();
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    // The request is the point of the screen — start it immediately.
    WidgetsBinding.instance.addPostFrameCallback((_) => _suggest());
  }

  Future<void> _suggest() async {
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final result =
          await ref.read(spendingRepositoryProvider).suggestCategories();
      setState(() {
        _result = result;
        _acceptedTx
          ..clear()
          ..addAll(result.suggestions.map((s) => s.transactionId));
        _acceptedRules
          ..clear()
          ..addAll(List.generate(result.rules.length, (i) => i));
        _busy = false;
        if (result.sentCount == 0) {
          _notice = 'Nothing to categorize — everything already has a category.';
        }
      });
    } catch (e) {
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  Future<void> _apply() async {
    final result = _result;
    if (result == null) return;
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final outcome =
          await ref.read(spendingRepositoryProvider).applyAiSuggestions(
                assignments: result.suggestions
                    .where((s) => _acceptedTx.contains(s.transactionId))
                    .toList(),
                rules: [
                  for (var i = 0; i < result.rules.length; i++)
                    if (_acceptedRules.contains(i)) result.rules[i],
                ],
              );
      ref.invalidate(spendingReportProvider);
      ref.invalidate(categoriesProvider);
      ref.invalidate(categoryRulesProvider);
      ref.invalidate(transactionsProvider);
      messenger.showSnackBar(SnackBar(
        content: Text('${outcome['assigned']} categorized, '
            '${outcome['rules_created']} rules created'),
      ));
      if (mounted) Navigator.pop(context);
    } catch (e) {
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }

  /// Everything (suggestions + rules) currently ticked?
  bool get _allSelected {
    final result = _result;
    if (result == null) return false;
    return _acceptedTx.length == result.suggestions.length &&
        _acceptedRules.length == result.rules.length;
  }

  void _toggleAll() {
    final result = _result;
    if (result == null) return;
    setState(() {
      if (_allSelected) {
        _acceptedTx.clear();
        _acceptedRules.clear();
      } else {
        _acceptedTx
          ..clear()
          ..addAll(result.suggestions.map((s) => s.transactionId));
        _acceptedRules
          ..clear()
          ..addAll(List.generate(result.rules.length, (i) => i));
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    final selected = _acceptedTx.length + _acceptedRules.length;

    return Scaffold(
      appBar: AppBar(
        title: const Text('AI suggestions'),
        actions: [
          if (result != null && result.suggestions.isNotEmpty)
            IconButton(
              // Check-based glyphs read clearer than the abstract
              // select_all/deselect squares.
              icon: Icon(_allSelected ? Icons.remove_done : Icons.done_all),
              tooltip: _allSelected ? 'Deselect all' : 'Select all',
              onPressed: _busy ? null : _toggleAll,
            ),
          if (result != null)
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Ask again',
              onPressed: _busy ? null : _suggest,
            ),
        ],
      ),
      body: _busy && result == null
          ? const Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: 12),
                  Text('Asking Gemini…'),
                ],
              ),
            )
          : _error != null
              ? _ErrorBody(message: _error!, onRetry: _suggest)
              : result == null
                  ? const SizedBox.shrink()
                  : _Review(
                      result: result,
                      notice: _notice,
                      acceptedTx: _acceptedTx,
                      acceptedRules: _acceptedRules,
                      scrollController: _scrollController,
                      onToggleTx: (id) => setState(() =>
                          _acceptedTx.contains(id)
                              ? _acceptedTx.remove(id)
                              : _acceptedTx.add(id)),
                      onToggleRule: (i) => setState(() =>
                          _acceptedRules.contains(i)
                              ? _acceptedRules.remove(i)
                              : _acceptedRules.add(i)),
                      onToggleAllRules: (enabled) => setState(() {
                        _acceptedRules.clear();
                        if (enabled) {
                          _acceptedRules.addAll(
                              List.generate(result.rules.length, (i) => i));
                        }
                      }),
                    ),
      bottomNavigationBar: result == null ||
              (result.suggestions.isEmpty && result.rules.isEmpty)
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton(
                  onPressed: _busy || selected == 0 ? null : _apply,
                  // Break the count down so applied rules are never invisible:
                  // "121" hid that 31 of them were rule proposals.
                  child: Text(result.rules.isEmpty
                      ? 'Apply selected ($selected)'
                      : 'Apply selected (${_acceptedTx.length} categories · '
                          '${_acceptedRules.length} rules)'),
                ),
              ),
            ),
    );
  }
}

class _Review extends StatelessWidget {
  final AiSuggestResponse result;
  final String? notice;
  final Set<int> acceptedTx;
  final Set<int> acceptedRules;
  final ScrollController scrollController;
  final void Function(int) onToggleTx;
  final void Function(int) onToggleRule;
  final void Function(bool) onToggleAllRules;

  const _Review({
    required this.result,
    required this.notice,
    required this.acceptedTx,
    required this.acceptedRules,
    required this.scrollController,
    required this.onToggleTx,
    required this.onToggleRule,
    required this.onToggleAllRules,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return ListView(
      controller: scrollController,
      children: [
        if (notice != null)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(notice!),
          ),
        // The rules section sits BELOW the (often long) suggestion list, where
        // it was routinely scrolled past — announce it up top, with a switch
        // to skip rule creation entirely and a tap-to-jump for reviewing them.
        if (result.rules.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Card(
              color: theme.colorScheme.primaryContainer,
              margin: EdgeInsets.zero,
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => scrollController.animateTo(
                  scrollController.position.maxScrollExtent,
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeOut,
                ),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
                  child: Row(
                    children: [
                      Icon(Icons.auto_awesome,
                          size: 18,
                          color: theme.colorScheme.onPrimaryContainer),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Also create ${result.rules.length} rule'
                          '${result.rules.length == 1 ? '' : 's'} for '
                          'recurring merchants — they categorize future '
                          'transactions without AI. Tap to review.',
                          style: TextStyle(
                              color: theme.colorScheme.onPrimaryContainer),
                        ),
                      ),
                      // Off = skip rule creation for this round entirely.
                      Switch(
                        value: acceptedRules.isNotEmpty,
                        onChanged: onToggleAllRules,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        if (result.suggestions.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
            child: Text(
              'Categories for ${result.suggestions.length} of '
              '${result.sentCount} transactions'
              '${result.totalUncategorized > result.sentCount ? ' · ${result.totalUncategorized - result.sentCount} more remain uncategorized' : ''}',
              style: theme.textTheme.labelMedium,
            ),
          ),
          for (final s in result.suggestions)
            CheckboxListTile(
              value: acceptedTx.contains(s.transactionId),
              onChanged: (_) => onToggleTx(s.transactionId),
              title: Builder(builder: (context) {
                // Same rule as the transaction list: the IBAN prefix carries
                // no meaning on screen — show the name or the booking text.
                final name = stripLeadingIban(s.counterparty);
                return Text(
                  name.isEmpty ? s.description : name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                );
              }),
              // The category chip lives UNDER the entry, not beside it — as
              // `secondary` it squeezed long merchant names into a sliver
              // whenever the category name was long.
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${s.bookingDate} · '
                      '${formatCurrencyExact(double.tryParse(s.amount) ?? 0, s.currency)}'),
                  const SizedBox(height: 4),
                  _CategoryLabel(name: s.category, isNew: s.isNewCategory),
                ],
              ),
            ),
        ],
        if (result.rules.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
            child: Text(
              'Rules — these categorize future transactions without AI',
              style: theme.textTheme.labelMedium,
            ),
          ),
          for (var i = 0; i < result.rules.length; i++)
            CheckboxListTile(
              value: acceptedRules.contains(i),
              onChanged: (_) => onToggleRule(i),
              title: Text(result.rules[i].matchText),
              subtitle: Text('→ ${result.rules[i].category}'),
              secondary: result.rules[i].isNewCategory
                  ? const _CategoryLabel(name: 'NEW', isNew: true)
                  : null,
            ),
        ],
        if (result.usage != null)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Tokens: ${result.usage!.inputTokens} in / '
              '${result.usage!.outputTokens} out'
              '${result.usage!.estimatedCostUsd != null ? ' — about \$${result.usage!.estimatedCostUsd}' : ''}',
              style: theme.textTheme.labelSmall,
            ),
          ),
      ],
    );
  }
}

class _CategoryLabel extends StatelessWidget {
  final String name;
  final bool isNew;
  const _CategoryLabel({required this.name, required this.isNew});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(
          color: isNew ? const Color(0xFFA3E635) : theme.dividerColor,
        ),
      ),
      child: Text(
        name,
        style: theme.textTheme.labelSmall?.copyWith(
          color: isNew ? const Color(0xFFA3E635) : null,
        ),
      ),
    );
  }
}

class _ErrorBody extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorBody({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 60),
        Icon(Icons.error_outline,
            color: Theme.of(context).colorScheme.error, size: 40),
        const SizedBox(height: 12),
        Text(message, textAlign: TextAlign.center),
        const SizedBox(height: 16),
        Center(
          child: OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
        ),
      ],
    );
  }
}
