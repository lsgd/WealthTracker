import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/transactions.dart';
import '../providers/spending_provider.dart';
import '../widgets/ai_categorization_card.dart';

/// Rules and AI configuration for the spending insight.
///
/// Rules are evaluated top to bottom and the first match wins, so the list is
/// reorderable — a specific rule has to be able to sit above a broader one.
class SpendingConfigScreen extends ConsumerWidget {
  const SpendingConfigScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rules = ref.watch(categoryRulesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Spending settings')),
      body: ListView(
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 16, 16, 4),
            child: Text('Rules', style: TextStyle(fontWeight: FontWeight.w600)),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(
              'Match text is compared against counterparty and description. '
              'Checked top to bottom — the first match wins, so drag to reorder. '
              'New rules also apply to transactions that are still uncategorized.',
              style: TextStyle(fontSize: 12),
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
            data: (list) => _RuleList(rules: list),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            child: OutlinedButton.icon(
              onPressed: () => _addRule(context, ref),
              icon: const Icon(Icons.add),
              label: const Text('Add rule'),
            ),
          ),
          const Divider(),
          const AiCategorizationCard(),
        ],
      ),
    );
  }

  Future<void> _addRule(BuildContext context, WidgetRef ref) async {
    final categories = await ref.read(categoriesProvider.future);
    if (!context.mounted) return;
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => _RuleDialog(categories: categories),
    );
    if (created == true) {
      ref.invalidate(categoryRulesProvider);
      ref.invalidate(categoriesProvider);
      ref.invalidate(spendingReportProvider);
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
          title: Text(rule.matchText),
          subtitle: Text(
            [
              '→ ${rule.categoryName ?? ''}',
              if (rule.spreadMonths > 1) 'spread over ${rule.spreadMonths} months',
            ].join(' · '),
          ),
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

/// Create a rule, optionally creating its category in the same step.
class _RuleDialog extends ConsumerStatefulWidget {
  final List<TransactionCategory> categories;
  const _RuleDialog({required this.categories});

  @override
  ConsumerState<_RuleDialog> createState() => _RuleDialogState();
}

class _RuleDialogState extends ConsumerState<_RuleDialog> {
  final _matchController = TextEditingController();
  final _newCategoryController = TextEditingController();
  int? _categoryId;
  bool _newCategory = false;
  int _spread = 1;
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _matchController.dispose();
    _newCategoryController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('New rule'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _matchController,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Match text',
                hintText: 'e.g. rewe',
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<Object?>(
              initialValue: _newCategory ? 'new' : _categoryId,
              decoration: const InputDecoration(labelText: 'Category'),
              items: [
                for (final c in widget.categories)
                  DropdownMenuItem(value: c.id, child: Text(c.name)),
                const DropdownMenuItem(value: 'new', child: Text('New category…')),
              ],
              onChanged: (value) => setState(() {
                _newCategory = value == 'new';
                _categoryId = value is int ? value : null;
              }),
            ),
            if (_newCategory) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _newCategoryController,
                decoration: const InputDecoration(labelText: 'New category name'),
              ),
            ],
            const SizedBox(height: 12),
            DropdownButtonFormField<int>(
              initialValue: _spread,
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
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
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
          child: Text(_saving ? 'Saving…' : 'Create'),
        ),
      ],
    );
  }

  Future<void> _save() async {
    final matchText = _matchController.text.trim();
    if (matchText.isEmpty) {
      setState(() => _error = 'Enter the text to match.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final repository = ref.read(spendingRepositoryProvider);
      var categoryId = _categoryId;
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
          _error = 'Pick a category.';
        });
        return;
      }
      await repository.createRule(
        matchText: matchText,
        categoryId: categoryId,
        spreadMonths: _spread,
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() {
        _saving = false;
        _error = '$e';
      });
    }
  }
}
