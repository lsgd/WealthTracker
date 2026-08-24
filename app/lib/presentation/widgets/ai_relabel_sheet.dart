import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/ai_categorization.dart';
import '../providers/spending_provider.dart';

/// Review sheet for the fix-similar-with-AI flow.
///
/// Asks Gemini which of the user's transactions look like the one just
/// re-labeled by hand and should get the same category. Everything is a
/// proposal: each entry can be unticked, and nothing persists until Apply.
/// Pops with the number of applied fixes (null = nothing applied).
class AiRelabelSheet extends ConsumerStatefulWidget {
  final int transactionId;
  final String categoryName;

  const AiRelabelSheet({
    super.key,
    required this.transactionId,
    required this.categoryName,
  });

  @override
  ConsumerState<AiRelabelSheet> createState() => _AiRelabelSheetState();
}

class _AiRelabelSheetState extends ConsumerState<AiRelabelSheet> {
  AiSuggestResponse? _response;
  String? _error;
  bool _applying = false;
  final Set<int> _unticked = {};
  final Set<String> _untickedRules = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final response = await ref
          .read(spendingRepositoryProvider)
          .relabelSimilar(widget.transactionId);
      if (mounted) setState(() => _response = response);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Future<void> _apply() async {
    final response = _response!;
    final assignments = [
      for (final s in response.suggestions)
        if (!_unticked.contains(s.transactionId)) s,
    ];
    final rules = [
      for (final r in response.rules)
        if (!_untickedRules.contains(r.matchText)) r,
    ];
    setState(() => _applying = true);
    try {
      await ref.read(spendingRepositoryProvider).applyAiSuggestions(
            assignments: assignments,
            rules: rules,
          );
      ref.invalidate(transactionsProvider);
      ref.invalidate(spendingReportProvider);
      if (rules.isNotEmpty) ref.invalidate(categoryRulesProvider);
      if (mounted) Navigator.pop(context, assignments.length);
    } catch (e) {
      if (mounted) {
        setState(() {
          _applying = false;
          _error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final response = _response;

    final Widget body;
    if (_error != null) {
      body = Padding(
        padding: const EdgeInsets.all(24),
        child: Text(_error!, textAlign: TextAlign.center),
      );
    } else if (response == null) {
      body = const Padding(
        padding: EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 16),
            Text('Asking Gemini for similar transactions…'),
          ],
        ),
      );
    } else if (response.suggestions.isEmpty && response.rules.isEmpty) {
      body = const Padding(
        padding: EdgeInsets.all(24),
        child: Text(
          'No similar transactions found.',
          textAlign: TextAlign.center,
        ),
      );
    } else {
      final checkedCount = response.suggestions
          .where((s) => !_unticked.contains(s.transactionId))
          .length;
      body = Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final s in response.suggestions)
                  CheckboxListTile(
                    value: !_unticked.contains(s.transactionId),
                    onChanged: (checked) => setState(() {
                      checked == true
                          ? _unticked.remove(s.transactionId)
                          : _unticked.add(s.transactionId);
                    }),
                    title: Text(
                      s.counterparty.isEmpty ? s.description : s.counterparty,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(
                      '${s.bookingDate} · ${s.amount} ${s.currency}\n'
                      '${s.currentCategory ?? 'Uncategorized'} → ${s.category}',
                      maxLines: 2,
                    ),
                    isThreeLine: true,
                    dense: true,
                  ),
                // A rule keeps future transactions of this merchant out of
                // AI rounds entirely.
                for (final r in response.rules)
                  SwitchListTile(
                    value: !_untickedRules.contains(r.matchText),
                    onChanged: (on) => setState(() {
                      on
                          ? _untickedRules.remove(r.matchText)
                          : _untickedRules.add(r.matchText);
                    }),
                    title: Text('Rule: "${r.matchText}" → ${r.category}'),
                    subtitle: Text(r.shadowedMatchText == null
                        ? 'Categorizes future matches automatically'
                        // First match wins — the fix only works ahead of the
                        // rule that caused the mislabel.
                        : 'Checked before your "${r.shadowedMatchText}" rule, '
                            'which caused this'),
                    dense: true,
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Reviewed ${response.sentCount} candidates',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                FilledButton(
                  onPressed: _applying ||
                          (checkedCount == 0 &&
                              response.rules.length == _untickedRules.length)
                      ? null
                      : _apply,
                  child: _applying
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text('Apply ($checkedCount)'),
                ),
              ],
            ),
          ),
        ],
      );
    }

    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            child: Text(
              'Similar to fix as "${widget.categoryName}"',
              style: theme.textTheme.titleMedium,
            ),
          ),
          body,
        ],
      ),
    );
  }
}
