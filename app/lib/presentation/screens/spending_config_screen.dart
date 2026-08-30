import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/transactions.dart';
import '../providers/spending_provider.dart';
import '../widgets/ai_categorization_card.dart';
import '../widgets/ai_consolidate_sheet.dart';
import '../widgets/rule_dialog.dart';

/// Rules and AI configuration for the spending insight.
///
/// Rules default to a compact by-category view; the flat first-match-wins
/// order (with drag-to-reorder) is one toggle away for the rare
/// specific-before-generic conflict.
class SpendingConfigScreen extends ConsumerStatefulWidget {
  const SpendingConfigScreen({super.key});

  @override
  ConsumerState<SpendingConfigScreen> createState() =>
      _SpendingConfigScreenState();
}

class _SpendingConfigScreenState extends ConsumerState<SpendingConfigScreen> {
  bool _orderView = false;

  @override
  Widget build(BuildContext context) {
    final rules = ref.watch(categoryRulesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Spending settings')),
      body: ListView(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 8, 0),
            child: Row(
              children: [
                const Text('Rules',
                    style: TextStyle(fontWeight: FontWeight.w600)),
                const Spacer(),
                TextButton.icon(
                  onPressed: () => setState(() => _orderView = !_orderView),
                  icon: Icon(_orderView ? Icons.category_outlined : Icons.swap_vert,
                      size: 18),
                  label: Text(_orderView ? 'Grouped' : 'Order'),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(
              _orderView
                  ? 'Checked top to bottom — the first match wins, so drag a '
                      'specific rule above a broader one.'
                  : 'Match text is compared against counterparty and '
                      'description; the first matching rule wins. Order only '
                      'matters when rules overlap — switch to Order to drag.',
              style: const TextStyle(fontSize: 12),
            ),
          ),
          rules.when(
            loading: () => const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
            error: (e, _) => Padding(
              padding: const EdgeInsets.all(16),
              child: Text('$e'),
            ),
            data: (list) => _orderView
                ? _RuleList(rules: list)
                : _GroupedRuleList(rules: list),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            child: Row(
              children: [
                OutlinedButton.icon(
                  onPressed: () => _addRule(context, ref),
                  icon: const Icon(Icons.add),
                  label: const Text('Add rule'),
                ),
                const SizedBox(width: 8),
                // AI pass that merges duplicate/dead rules — only meaningful
                // once there are at least two.
                if ((rules.value?.length ?? 0) >= 2)
                  OutlinedButton.icon(
                    onPressed: () => _consolidate(context, ref, rules.value!),
                    icon: const Icon(Icons.compress),
                    label: const Text('Consolidate'),
                  ),
              ],
            ),
          ),
          const Divider(),
          const _CategoriesSection(),
          const Divider(),
          const AiCategorizationCard(),
        ],
      ),
    );
  }

  Future<void> _consolidate(
      BuildContext context, WidgetRef ref, List<CategoryRule> rules) async {
    final count = await showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => AiConsolidateSheet(currentRules: rules),
    );
    if (count != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Rule set replaced: $count rules')),
      );
    }
  }

  Future<void> _addRule(BuildContext context, WidgetRef ref) =>
      editRule(context, ref);
}

/// Manage the flat category list: rename or delete.
///
/// Renaming keeps every transaction and rule pointing at the category.
/// Deleting makes its transactions uncategorized and removes rules that map
/// to it (the backend cascades those).
class _CategoriesSection extends ConsumerWidget {
  const _CategoriesSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final categories = ref.watch(categoriesProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 16, 16, 4),
          child: Text('Categories',
              style: TextStyle(fontWeight: FontWeight.w600)),
        ),
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(
            'Renaming keeps all assignments. Deleting makes its transactions '
            'uncategorized and removes rules that map to it.',
            style: TextStyle(fontSize: 12),
          ),
        ),
        categories.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(24),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (e, _) => Padding(
            padding: const EdgeInsets.all(16),
            child: Text('$e'),
          ),
          data: (list) => list.isEmpty
              ? const Padding(
                  padding: EdgeInsets.fromLTRB(16, 8, 16, 16),
                  child: Text('No categories yet.'),
                )
              : Column(
                  children: [
                    for (final category in list)
                      ListTile(
                        dense: true,
                        title: Text(category.name),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              icon: const Icon(Icons.edit_outlined, size: 20),
                              tooltip: 'Rename',
                              onPressed: () =>
                                  _rename(context, ref, category),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, size: 20),
                              tooltip: 'Delete',
                              onPressed: () =>
                                  _delete(context, ref, category),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
        ),
        const SizedBox(height: 8),
      ],
    );
  }

  /// Refresh everything a category name/existence appears in.
  void _invalidate(WidgetRef ref) {
    ref.invalidate(categoriesProvider);
    ref.invalidate(categoryRulesProvider);
    ref.invalidate(spendingReportProvider);
    ref.invalidate(transactionsProvider);
  }

  Future<void> _rename(
      BuildContext context, WidgetRef ref, TransactionCategory category) async {
    final controller = TextEditingController(text: category.name);
    final messenger = ScaffoldMessenger.of(context);
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename category'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Name'),
          onSubmitted: (value) => Navigator.pop(context, value.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('Rename'),
          ),
        ],
      ),
    );
    if (name == null || name.isEmpty || name == category.name) return;
    try {
      await ref
          .read(spendingRepositoryProvider)
          .renameCategory(category.id, name);
      _invalidate(ref);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _delete(
      BuildContext context, WidgetRef ref, TransactionCategory category) async {
    final messenger = ScaffoldMessenger.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete "${category.name}"?'),
        content: const Text(
          'Its transactions become uncategorized and rules mapping to it '
          'are deleted. This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(spendingRepositoryProvider).deleteCategory(category.id);
      _invalidate(ref);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

/// Compact default view: rules bucketed by target category, one chip each.
class _GroupedRuleList extends ConsumerWidget {
  final List<CategoryRule> rules;
  const _GroupedRuleList({required this.rules});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (rules.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Text('No rules yet.'),
      );
    }

    final groups = <String, List<CategoryRule>>{};
    for (final rule in rules) {
      final label =
          rule.isTransfer ? 'Transfer (excluded)' : (rule.categoryName ?? '—');
      groups.putIfAbsent(label, () => []).add(rule);
    }
    final entries = groups.entries.toList()
      ..sort((a, b) {
        // Transfer group last, otherwise alphabetical.
        final aTransfer = a.value.first.isTransfer ? 1 : 0;
        final bTransfer = b.value.first.isTransfer ? 1 : 0;
        return aTransfer != bTransfer
            ? aTransfer - bTransfer
            : a.key.compareTo(b.key);
      });
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final entry in entries)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${entry.key} (${entry.value.length})',
                    style: theme.textTheme.labelMedium),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final rule in entry.value)
                      InputChip(
                        label: Text(
                          (rule.isRegex
                                  ? '/${rule.matchText}/'
                                  : rule.matchText) +
                              (rule.spreadMonths > 1
                                  ? ' · /${rule.spreadMonths}m'
                                  : '') +
                              (rule.amountCondition != null
                                  ? ' · ${rule.amountCondition}'
                                  : ''),
                        ),
                        onPressed: () => editRule(context, ref, rule: rule),
                        onDeleted: () => _delete(context, ref, rule),
                      ),
                  ],
                ),
              ],
            ),
          ),
      ],
    );
  }

  Future<void> _delete(
      BuildContext context, WidgetRef ref, CategoryRule rule) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(spendingRepositoryProvider).deleteRule(rule.id);
      ref.invalidate(categoryRulesProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

class _RuleList extends ConsumerWidget {
  final List<CategoryRule> rules;
  const _RuleList({required this.rules});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (rules.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Text('No rules yet.'),
      );
    }

    return ReorderableListView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: rules.length,
      // onReorderItem (not onReorder) already accounts for the removed item,
      // so newIndex is the final index and needs no adjustment.
      onReorderItem: (oldIndex, newIndex) =>
          _reorder(context, ref, oldIndex, newIndex),
      itemBuilder: (context, index) {
        final rule = rules[index];
        return ListTile(
          key: ValueKey(rule.id),
          leading: Text('${index + 1}'),
          title: Text(rule.isRegex ? '/${rule.matchText}/' : rule.matchText),
          subtitle: Text(
            [
              '→ ${rule.isTransfer ? 'Transfer (excluded)' : rule.categoryName ?? ''}',
              if (rule.isRegex) 'regex',
              if (rule.spreadMonths > 1) 'spread over ${rule.spreadMonths} months',
              if (rule.amountCondition != null) rule.amountCondition!,
            ].join(' · '),
          ),
          onTap: () => editRule(context, ref, rule: rule),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                icon: const Icon(Icons.delete_outline),
                tooltip: 'Delete rule',
                onPressed: () => _delete(context, ref, rule),
              ),
              const Icon(Icons.drag_handle),
            ],
          ),
        );
      },
    );
  }

  Future<void> _reorder(
      BuildContext context, WidgetRef ref, int oldIndex, int newIndex) async {
    final next = [...rules];
    next.insert(newIndex, next.removeAt(oldIndex));

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(spendingRepositoryProvider)
          .reorderRules(next.map((r) => r.id).toList());
      ref.invalidate(categoryRulesProvider);
      ref.invalidate(spendingReportProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
      ref.invalidate(categoryRulesProvider);
    }
  }

  Future<void> _delete(
      BuildContext context, WidgetRef ref, CategoryRule rule) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(spendingRepositoryProvider).deleteRule(rule.id);
      ref.invalidate(categoryRulesProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}
