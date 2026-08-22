import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../../data/models/transactions.dart';
import '../providers/accounts_provider.dart';
import '../providers/spending_provider.dart';

/// All transactions across accounts, newest first, with manual categorization.
///
/// A collapsible filter narrows to one account and/or uncategorized entries.
/// Tapping a row opens the category/transfer sheet; the choice is stored as a
/// manual decision, so rules never overwrite it afterwards.
class TransactionsTab extends ConsumerWidget {
  const TransactionsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final transactions = ref.watch(transactionsProvider);
    final filter = ref.watch(transactionsFilterProvider);
    final accounts = ref.watch(accountsProvider).value ?? const [];
    final accountNames = {for (final a in accounts) a.id: a.name};

    return Column(
      children: [
        _FilterBar(filter: filter, accountNames: accountNames),
        Expanded(
          child: transactions.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => _Message(text: e.toString()),
            data: (data) {
              if (data.results.isEmpty) {
                return _Message(
                  text: filter.uncategorizedOnly
                      ? 'Nothing uncategorized — all done.'
                      : 'No transactions yet.',
                );
              }
              return RefreshIndicator(
                onRefresh: () async =>
                    ref.refresh(transactionsProvider.future),
                child: ListView.separated(
                  // +1 for the load-more footer.
                  itemCount: data.results.length + (data.hasMore ? 1 : 0),
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    if (index == data.results.length) {
                      return _LoadMoreFooter(state: data);
                    }
                    final tx = data.results[index];
                    return _TransactionTile(
                      transaction: tx,
                      // Name the account only when the list mixes accounts.
                      accountName: filter.accountId == null
                          ? accountNames[tx.account]
                          : null,
                    );
                  },
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// Collapsed: one row summarizing the active filters. Expanded: the account
/// picker and the uncategorized switch.
class _FilterBar extends ConsumerWidget {
  final TransactionsFilter filter;
  final Map<int, String> accountNames;

  const _FilterBar({required this.filter, required this.accountNames});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(transactionsFilterProvider.notifier);
    final summary = [
      filter.accountId == null
          ? 'All accounts'
          : (accountNames[filter.accountId] ?? 'One account'),
      if (filter.uncategorizedOnly) 'only uncategorized',
    ].join(' · ');

    return ExpansionTile(
      leading: const Icon(Icons.filter_list),
      title: Text(summary, style: Theme.of(context).textTheme.bodyMedium),
      dense: true,
      shape: const Border(),
      collapsedShape: const Border(),
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      children: [
        DropdownButtonFormField<int?>(
          initialValue: filter.accountId,
          decoration: const InputDecoration(
            labelText: 'Account',
            isDense: true,
            border: OutlineInputBorder(),
          ),
          items: [
            const DropdownMenuItem<int?>(
                value: null, child: Text('All accounts')),
            for (final entry in accountNames.entries)
              DropdownMenuItem<int?>(
                  value: entry.key, child: Text(entry.value)),
          ],
          onChanged: notifier.setAccount,
        ),
        SwitchListTile(
          title: const Text('Only uncategorized'),
          contentPadding: EdgeInsets.zero,
          value: filter.uncategorizedOnly,
          onChanged: notifier.setUncategorizedOnly,
        ),
      ],
    );
  }
}

class _LoadMoreFooter extends ConsumerWidget {
  final TransactionsState state;
  const _LoadMoreFooter({required this.state});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Center(
        child: state.loadingMore
            ? const SizedBox(
                width: 20, height: 20,
                child: CircularProgressIndicator(strokeWidth: 2))
            : TextButton(
                onPressed: () =>
                    ref.read(transactionsProvider.notifier).loadMore(),
                child: Text(
                    'Load more (${state.results.length}/${state.totalCount})'),
              ),
      ),
    );
  }
}

class _TransactionTile extends ConsumerWidget {
  final TransactionRecord transaction;
  final String? accountName;

  const _TransactionTile({required this.transaction, this.accountName});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    // The IBAN prefix some feeds put in the counterparty says nothing about
    // WHAT the money was for — show the name, and lean on the description.
    final name = stripLeadingIban(transaction.counterparty);
    final subtitle = [
      transaction.bookingDate,
      if (transaction.description.isNotEmpty) transaction.description,
    ].join(' · ');

    return Opacity(
      // Transfers between own accounts are excluded from spending; dim them so
      // it is obvious why they never show up in the charts.
      opacity: transaction.isTransfer ? 0.55 : 1,
      child: ListTile(
        title: Text(
          name.isEmpty
              ? (transaction.description.isEmpty
                  ? 'Transaction'
                  : transaction.description)
              : name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Two lines: the description is the actual justification of the
            // booking, so give it room instead of truncating it to a sliver.
            Text(subtitle, maxLines: 2, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              children: [
                _Chip(
                  label: transaction.categoryName ?? 'Uncategorized',
                  highlighted: transaction.categoryName != null,
                ),
                if (accountName != null) _Chip(label: accountName!),
                if (transaction.isTransfer) const _Chip(label: 'Transfer'),
                if (transaction.spreadMonths > 1)
                  _Chip(label: '/${transaction.spreadMonths}m'),
              ],
            ),
          ],
        ),
        isThreeLine: true,
        trailing: Text(
          formatCurrency(transaction.value, transaction.currency),
          style: theme.textTheme.bodyMedium?.copyWith(
            color: transaction.isExpense
                ? theme.colorScheme.error
                : const Color(0xFF34D399),
            fontWeight: FontWeight.w600,
          ),
        ),
        onTap: () => _pickCategory(context, ref),
      ),
    );
  }

  Future<void> _pickCategory(BuildContext context, WidgetRef ref) async {
    final categories = await ref.read(categoriesProvider.future);
    if (!context.mounted) return;

    final choice = await showModalBottomSheet<_SheetChoice>(
      context: context,
      showDragHandle: true,
      builder: (context) => ListView(
        shrinkWrap: true,
        children: [
          // Transfers between own accounts are excluded from spending. Manual
          // marking is the only way in for transfers auto-detection cannot see
          // (e.g. a wire to a broker without a transaction feed).
          SwitchListTile(
            title: const Text('Transfer between own accounts'),
            subtitle: const Text('Excluded from the spending report'),
            value: transaction.isTransfer,
            onChanged: (value) =>
                Navigator.pop(context, _SheetChoice.transfer(value)),
          ),
          const Divider(height: 1),
          const ListTile(
            dense: true,
            title: Text('Category'),
          ),
          for (final category in categories)
            ListTile(
              title: Text(category.name),
              trailing: category.id == transaction.category
                  ? const Icon(Icons.check)
                  : null,
              onTap: () =>
                  Navigator.pop(context, _SheetChoice.category(category.id)),
            ),
          if (transaction.category != null)
            ListTile(
              leading: const Icon(Icons.clear),
              title: const Text('Remove category'),
              onTap: () => Navigator.pop(context, _SheetChoice.category(null)),
            ),
        ],
      ),
    );
    if (choice == null || !context.mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      final repo = ref.read(spendingRepositoryProvider);
      final TransactionRecord updated;
      if (choice.isTransferChoice) {
        updated = await repo.setTransfer(transaction.id,
            isTransfer: choice.transferValue!);
      } else {
        updated = await repo.classifyTransaction(transaction.id,
            categoryId: choice.categoryId);
      }
      // In-place update keeps scroll position and loaded pages. Exception:
      // with the uncategorized filter on, a categorized entry no longer
      // belongs in the list — reload to drop it.
      final filter = ref.read(transactionsFilterProvider);
      if (filter.uncategorizedOnly && updated.category != null) {
        ref.invalidate(transactionsProvider);
      } else {
        ref.read(transactionsProvider.notifier).replace(updated);
      }
      ref.invalidate(spendingReportProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

/// What the bottom sheet resolved to: a category assignment or a transfer flip.
class _SheetChoice {
  final int? categoryId;
  final bool? transferValue;

  const _SheetChoice.category(this.categoryId) : transferValue = null;
  const _SheetChoice.transfer(this.transferValue) : categoryId = null;

  bool get isTransferChoice => transferValue != null;
}

class _Chip extends StatelessWidget {
  final String label;
  final bool highlighted;
  const _Chip({required this.label, this.highlighted = false});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: theme.dividerColor),
        color: highlighted
            ? theme.colorScheme.primary.withValues(alpha: 0.12)
            : null,
      ),
      child: Text(label, style: theme.textTheme.labelSmall),
    );
  }
}

class _Message extends StatelessWidget {
  final String text;
  const _Message({required this.text});

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: [
        const SizedBox(height: 100),
        Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(text, textAlign: TextAlign.center),
          ),
        ),
      ],
    );
  }
}
