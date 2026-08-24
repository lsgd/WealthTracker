import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/ai_categorization.dart';
import '../../data/models/transactions.dart';
import '../providers/spending_provider.dart';

/// Review sheet for AI rule consolidation.
///
/// Gemini proposes a smaller equivalent rule set (merged duplicates, dropped
/// dead rules); this shows the resulting set plus every current rule that
/// would disappear, and replaces the whole set only on Apply. Pops with the
/// new rule count (null = not applied).
class AiConsolidateSheet extends ConsumerStatefulWidget {
  /// The current rules, to name what a merged rule replaces.
  final List<CategoryRule> currentRules;

  const AiConsolidateSheet({super.key, required this.currentRules});

  @override
  ConsumerState<AiConsolidateSheet> createState() => _AiConsolidateSheetState();
}

class _AiConsolidateSheetState extends ConsumerState<AiConsolidateSheet> {
  AiConsolidateResponse? _response;
  String? _error;
  bool _applying = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final response =
          await ref.read(spendingRepositoryProvider).consolidateRules();
      if (mounted) setState(() => _response = response);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Future<void> _apply() async {
    setState(() => _applying = true);
    try {
      await ref
          .read(spendingRepositoryProvider)
          .replaceRules(_response!.rules);
      ref.invalidate(categoryRulesProvider);
      ref.invalidate(transactionsProvider);
      ref.invalidate(spendingReportProvider);
      if (mounted) Navigator.pop(context, _response!.rules.length);
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
            Text('Asking Gemini to consolidate the rules…'),
          ],
        ),
      );
    } else if (response.rules.isEmpty ||
        response.afterCount >= response.beforeCount) {
      body = const Padding(
        padding: EdgeInsets.all(24),
        child: Text(
          'Nothing to consolidate — the rule set is already minimal.',
          textAlign: TextAlign.center,
        ),
      );
    } else {
      // Current rules that appear in no surviving rule's sources are dropped
      // outright (dead or superseded) — surface them, they deserve a look.
      final surviving = {
        for (final r in response.rules) ...r.sources,
      };
      final dropped = [
        for (final r in widget.currentRules)
          if (!surviving.contains(r.id)) r,
      ];

      body = Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final r in response.rules)
                  ListTile(
                    dense: true,
                    leading: const Icon(Icons.rule, size: 20),
                    title: Text('"${r.matchText}" → ${r.category}'),
                    subtitle: r.sources.length > 1
                        ? Text('Merges ${r.sources.length} rules')
                        : null,
                  ),
                if (dropped.isNotEmpty) ...[
                  const Divider(height: 1),
                  ListTile(
                    dense: true,
                    title: Text('Removed', style: theme.textTheme.labelLarge),
                  ),
                  for (final r in dropped)
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.delete_outline, size: 20),
                      title: Text(
                        '"${r.matchText}" → ${r.categoryName ?? '?'}',
                        style: const TextStyle(
                            decoration: TextDecoration.lineThrough),
                      ),
                    ),
                ],
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    '${response.beforeCount} rules → ${response.afterCount}',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                FilledButton(
                  onPressed: _applying ? null : _apply,
                  child: _applying
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Replace rules'),
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
            child: Text('Consolidate rules', style: theme.textTheme.titleMedium),
          ),
          body,
        ],
      ),
    );
  }
}
