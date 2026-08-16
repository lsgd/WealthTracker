import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../../data/models/transactions.dart';
import '../providers/accounts_provider.dart';
import '../providers/spending_provider.dart';

/// Transactions of one account, with manual categorization.
///
/// Tapping a row opens a category picker; the choice is stored as a manual
/// decision, so rules never overwrite it afterwards.
class TransactionsTab extends ConsumerWidget {
  const TransactionsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accounts = ref.watch(accountsProvider);

    return accounts.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _Message(text: e.toString()),
      data: (list) {
        final selectable = list.where((a) => !a.isManual).toList();
        if (selectable.isEmpty) {
          return const _Message(
            text: 'No account with a transaction feed yet.',
          );
        }
        final selected = ref.watch(transactionsAccountProvider) ??
            selectable.first.id;

        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: DropdownButtonFormField<int>(
                initialValue: selected,
                decoration: const InputDecoration(
                  labelText: 'Account',
                  isDense: true,
                  border: OutlineInputBorder(),
                ),
                items: [
                  for (final a in selectable)
                    DropdownMenuItem(value: a.id, child: Text(a.name)),
                ],
                onChanged: (value) =>
                    ref.read(transactionsAccountProvider.notifier).set(value),
              ),
            ),
            Expanded(child: _TransactionList(accountId: selected)),
          ],
        );
      },
    );
  }
}

class _TransactionList extends ConsumerWidget {
  final int accountId;
  const _TransactionList({required this.accountId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final page = ref.watch(accountTransactionsProvider(accountId));

    return page.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _Message(text: e.toString()),
      data: (data) {
        if (data.results.isEmpty) {
          return const _Message(text: 'No transactions for this account.');
        }
        return RefreshIndicator(
          onRefresh: () async =>
              ref.refresh(accountTransactionsProvider(accountId).future),
          child: ListView.separated(
            itemCount: data.results.length,
            separatorBuilder: (_, _) => const Divider(height: 1),
            itemBuilder: (context, index) => _TransactionTile(
              transaction: data.results[index],
              accountId: accountId,
            ),
          ),
        );
      },
    );
  }
}

class _TransactionTile extends ConsumerWidget {
  final TransactionRecord transaction;
  final int accountId;

  const _TransactionTile({required this.transaction, required this.accountId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
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
          transaction.counterparty.isEmpty
              ? (transaction.description.isEmpty
                  ? 'Transaction'
                  : transaction.description)
              : transaction.counterparty,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              children: [
                _Chip(
                  label: transaction.categoryName ?? 'Uncategorized',
                  highlighted: transaction.categoryName != null,
                ),
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

    final choice = await showModalBottomSheet<_CategoryChoice>(
      context: context,
      showDragHandle: true,
      builder: (context) => ListView(
        shrinkWrap: true,
        children: [
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
                  Navigator.pop(context, _CategoryChoice(id: category.id)),
            ),
          if (transaction.category != null)
            ListTile(
              leading: const Icon(Icons.clear),
              title: const Text('Remove category'),
              onTap: () => Navigator.pop(context, const _CategoryChoice()),
            ),
        ],
      ),
    );
    if (choice == null || !context.mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(spendingRepositoryProvider)
          .classifyTransaction(transaction.id, categoryId: choice.id);
      ref.invalidate(accountTransactionsProvider(accountId));
      ref.invalidate(spendingReportProvider);
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

class _CategoryChoice {
  final int? id;
  const _CategoryChoice({this.id});
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
