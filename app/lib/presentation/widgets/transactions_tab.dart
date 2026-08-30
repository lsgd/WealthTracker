import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../../core/utils/periods.dart';
import '../../data/models/transactions.dart';
import '../../data/repositories/spending_repository.dart';
import '../providers/accounts_provider.dart';
import '../providers/spending_provider.dart';
import 'ai_relabel_sheet.dart';
import 'rule_dialog.dart';

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
        const _SearchField(),
        _FilterBar(filter: filter, accountNames: accountNames),
        Expanded(
          child: transactions.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => _Message(text: e.toString()),
            data: (data) {
              if (data.results.isEmpty) {
                return _Message(text: _emptyMessage(filter));
              }
              return NotificationListener<ScrollNotification>(
                // Endless scrolling: fetch the next page as the end comes
                // into reach. loadMore() itself ignores calls while a page
                // is in flight or everything is loaded.
                onNotification: (notification) {
                  if (data.hasMore &&
                      notification.metrics.extentAfter < 400) {
                    ref.read(transactionsProvider.notifier).loadMore();
                  }
                  return false;
                },
                child: RefreshIndicator(
                  onRefresh: () async =>
                      ref.refresh(transactionsProvider.future),
                  child: ListView.separated(
                    // +1 for the loading footer.
                    itemCount: data.results.length + (data.hasMore ? 1 : 0),
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      if (index == data.results.length) {
                        return const Padding(
                          padding: EdgeInsets.symmetric(vertical: 12),
                          child: Center(
                            child: SizedBox(
                              width: 20,
                              height: 20,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2),
                            ),
                          ),
                        );
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
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// Why the list is empty — which of the filters is responsible, so nobody
/// concludes there are no transactions when it is only the search.
String _emptyMessage(TransactionsFilter filter) {
  if (filter.search.isNotEmpty) return 'Nothing matches "${filter.search}".';
  return switch (filter.show) {
    TransactionsShow.uncategorized => 'Nothing uncategorized — all done.',
    TransactionsShow.transfers => 'No transfers here.',
    TransactionsShow.categories => 'Nothing in this category here.',
    TransactionsShow.everything => filter.month == null
        ? 'No transactions yet.'
        : 'No transactions in ${formatPeriod(filter.month!)}.',
  };
}

/// Free-text or amount search over the list.
///
/// Above the filter bar rather than inside it: recognizing a charge and not
/// its merchant is the common way into this list, and a control folded away
/// is a control nobody reaches for.
class _SearchField extends ConsumerStatefulWidget {
  const _SearchField();

  @override
  ConsumerState<_SearchField> createState() => _SearchFieldState();
}

class _SearchFieldState extends ConsumerState<_SearchField> {
  late final TextEditingController _controller;
  Timer? _debounce;

  /// Long enough that typing a merchant name is one request, short enough that
  /// the list has moved on before the eye leaves the field.
  static const _delay = Duration(milliseconds: 350);

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(
        text: ref.read(transactionsFilterProvider).search);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(_delay, () {
      ref.read(transactionsFilterProvider.notifier).setSearch(value.trim());
    });
  }

  @override
  Widget build(BuildContext context) {
    final search = ref.watch(transactionsFilterProvider.select((f) => f.search));
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: TextField(
        controller: _controller,
        textInputAction: TextInputAction.search,
        decoration: InputDecoration(
          isDense: true,
          prefixIcon: const Icon(Icons.search, size: 20),
          hintText: 'Search text or amount',
          border: const OutlineInputBorder(),
          suffixIcon: search.isEmpty && _controller.text.isEmpty
              ? null
              : IconButton(
                  icon: const Icon(Icons.clear, size: 20),
                  tooltip: 'Clear search',
                  onPressed: () {
                    _debounce?.cancel();
                    _controller.clear();
                    ref
                        .read(transactionsFilterProvider.notifier)
                        .setSearch('');
                  },
                ),
        ),
        onChanged: _onChanged,
        onSubmitted: (value) {
          _debounce?.cancel();
          ref.read(transactionsFilterProvider.notifier).setSearch(value.trim());
        },
      ),
    );
  }
}

/// Collapsed: one row summarizing the active filters. Expanded: the account
/// picker and what to show.
class _FilterBar extends ConsumerWidget {
  final TransactionsFilter filter;
  final Map<int, String> accountNames;

  const _FilterBar({required this.filter, required this.accountNames});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(transactionsFilterProvider.notifier);
    final categoryNames = {
      for (final c in ref.watch(categoriesProvider).value ?? const [])
        c.id: c.name,
    };
    final summary = [
      filter.accountId == null
          ? 'All accounts'
          : (accountNames[filter.accountId] ?? 'One account'),
      if (filter.month != null) formatPeriod(filter.month!),
      switch (filter.show) {
        TransactionsShow.uncategorized => 'only uncategorized',
        TransactionsShow.transfers => 'only transfers',
        TransactionsShow.categories => filter.categoryIds
            .map((id) => categoryNames[id] ?? 'category')
            .join(' + '),
        TransactionsShow.everything => null,
      },
    ].nonNulls.join(' · ');
    // Periods the report covers, newest first, plus the selected one (the
    // range can be shortened after a period was picked in Insights). The
    // labels carry their granularity — '2026-Q3' as readily as '2026-08'.
    final report = ref.watch(spendingReportProvider).value;
    final months = <String>{
      if (filter.month != null) filter.month!,
      ...?report?.months.reversed.map((m) => m.month),
    }.toList();

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
        const SizedBox(height: 8),
        DropdownButtonFormField<String?>(
          initialValue: filter.month,
          decoration: const InputDecoration(
            labelText: 'Period',
            isDense: true,
            border: OutlineInputBorder(),
          ),
          items: [
            const DropdownMenuItem<String?>(
                value: null, child: Text('All periods')),
            for (final month in months)
              DropdownMenuItem<String?>(
                  value: month, child: Text(formatPeriod(month))),
          ],
          onChanged: notifier.setMonth,
        ),
        const SizedBox(height: 8),
        // One control: a transaction is either awaiting a label or a transfer,
        // and drilling in from a category is a third answer to the same
        // question — parallel switches could ask for two at once.
        DropdownButtonFormField<TransactionsShow>(
          initialValue: filter.show,
          decoration: const InputDecoration(
            labelText: 'Show',
            isDense: true,
            border: OutlineInputBorder(),
          ),
          items: [
            const DropdownMenuItem(
              value: TransactionsShow.everything,
              child: Text('Everything'),
            ),
            const DropdownMenuItem(
              value: TransactionsShow.uncategorized,
              child: Text('Uncategorized only'),
            ),
            const DropdownMenuItem(
              value: TransactionsShow.transfers,
              child: Text('Transfers only'),
            ),
            // Only reachable by drilling in from a category, so it is offered
            // to keep rather than to pick.
            if (filter.show == TransactionsShow.categories)
              DropdownMenuItem(
                value: TransactionsShow.categories,
                child: Text(
                  filter.categoryIds
                      .map((id) => categoryNames[id] ?? 'category')
                      .join(' + '),
                ),
              ),
          ],
          onChanged: (value) {
            if (value != null) notifier.setShow(value);
          },
        ),
        const SizedBox(height: 8),
      ],
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

  /// Offered spreads, plus whatever the transaction already carries (a rule or
  /// Gemini can set any number, and SegmentedButton needs its selection listed).
  List<int> get _spreadOptions =>
      (<int>{1, 3, 6, 12, transaction.spreadMonths}.toList()..sort());

  Future<void> _pickCategory(BuildContext context, WidgetRef ref) async {
    final categories = await ref.read(categoriesProvider.future);
    if (!context.mounted) return;

    final choice = await showModalBottomSheet<_SheetChoice>(
      context: context,
      showDragHandle: true,
      // Sizes to the content instead of the default half screen: transfer,
      // spread and the categories together no longer fit in it.
      isScrollControlled: true,
      builder: (context) => ListView(
        shrinkWrap: true,
        children: [
          // Categorizing this one booking fixes one row; a rule fixes every
          // future booking of the same merchant, and this is the moment the
          // merchant is on screen.
          ListTile(
            leading: const Icon(Icons.playlist_add),
            title: const Text('Create a rule from this'),
            subtitle: const Text('Categorize every booking that matches'),
            onTap: () => Navigator.pop(context, const _SheetChoice.rule()),
          ),
          const Divider(height: 1),
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
          // Above the categories on purpose: the list can be long enough to
          // push anything below it out of the sheet, where nobody finds it.
          // A transfer is excluded from spending — nothing to amortize.
          if (!transaction.isTransfer) ...[
            const Divider(height: 1),
            const ListTile(
              dense: true,
              title: Text('Spread'),
              subtitle: Text('A yearly bill counts as one twelfth per month '
                  'in the normalized view'),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: SegmentedButton<int>(
                showSelectedIcon: false,
                segments: [
                  for (final months in _spreadOptions)
                    ButtonSegment(
                      value: months,
                      label: Text(months == 1 ? 'None' : '/${months}m'),
                    ),
                ],
                selected: {transaction.spreadMonths},
                onSelectionChanged: (values) =>
                    Navigator.pop(context, _SheetChoice.spread(values.first)),
              ),
            ),
          ],
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

    if (choice.isRuleChoice) {
      // Prefilled from the booking: the counterparty is what a rule for this
      // merchant matches on, and the category it already has is the one the
      // rule should hand to the rest.
      await editRule(
        context,
        ref,
        initialMatchText: stripLeadingIban(transaction.counterparty).isEmpty
            ? transaction.description
            : stripLeadingIban(transaction.counterparty),
        initialCategoryId: transaction.category,
        initialIsTransfer: transaction.isTransfer,
      );
      return;
    }

    final messenger = ScaffoldMessenger.of(context);
    // The tile can be disposed by the reload below while its snackbar is
    // still visible — the navigator's context outlives it for the sheet.
    final navigator = Navigator.of(context);
    try {
      final repo = ref.read(spendingRepositoryProvider);
      final Classified result;
      if (choice.isTransferChoice) {
        result = await repo.setTransfer(transaction.id,
            isTransfer: choice.transferValue!);
      } else if (choice.isSpreadChoice) {
        result = await repo.setSpread(transaction.id,
            spreadMonths: choice.spreadMonths!);
      } else {
        result = await repo.classifyTransaction(transaction.id,
            categoryId: choice.categoryId);
      }
      final updated = result.transaction;
      // Offer to propagate the correction to similar transactions — only for
      // an actual category assignment, and only when Gemini is configured.
      var offerAiFix = choice.isCategoryChoice && updated.categoryName != null;
      if (offerAiFix) {
        try {
          offerAiFix = (await ref.read(aiConfigProvider.future)).configured;
        } catch (_) {
          offerAiFix = false;
        }
      }
      // In-place update keeps scroll position and loaded pages. Exception:
      // with a filter the row no longer satisfies (uncategorized, or a
      // category it just left), it does not belong here — reload to drop it.
      final filter = ref.read(transactionsFilterProvider);
      final leftTheFilter = switch (filter.show) {
        TransactionsShow.uncategorized => updated.category != null,
        TransactionsShow.transfers => !updated.isTransfer,
        TransactionsShow.categories =>
          !filter.categoryIds.contains(updated.category),
        TransactionsShow.everything => false,
      };
      if (leftTheFilter) {
        ref.invalidate(transactionsProvider);
      } else {
        ref.read(transactionsProvider.notifier).replace(updated);
      }
      ref.invalidate(spendingReportProvider);
      // The rule behind this transaction now disagrees with the correction —
      // left alone it keeps sending every future booking of this merchant to
      // the old category. Ask before the AI offer, which is the weaker one.
      if (result.staleRule != null && navigator.mounted) {
        await _offerRuleUpdate(navigator.context, ref, result);
      } else if (offerAiFix) {
        _offerAiFix(navigator, messenger, updated);
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// Asks whether the correction should be applied to the matching rule too,
  /// which fixes every other transaction of the same merchant at once.
  Future<void> _offerRuleUpdate(
      BuildContext context, WidgetRef ref, Classified result) async {
    // Captured before the dialog: the tile can be disposed while it is open.
    final messenger = ScaffoldMessenger.of(context);
    final rule = result.staleRule!;
    final tx = result.transaction;
    final target = tx.isTransfer
        ? 'Transfer (excluded)'
        : (tx.categoryName ?? 'no category');
    final current = rule.isTransfer
        ? 'Transfer (excluded)'
        : (rule.categoryName ?? 'no category');

    final update = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Update the rule too?'),
        content: Text(
          'The rule "${rule.matchText}" classifies this transaction as '
          '$current, so the next booking that matches it lands there again. '
          'Point the rule at $target instead? Transactions you already '
          'categorized by hand keep their category.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Just this one'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Update the rule'),
          ),
        ],
      ),
    );
    if (update != true) return;

    try {
      await ref.read(spendingRepositoryProvider).updateRule(
            rule.id,
            categoryId: tx.isTransfer ? null : tx.category,
            spreadMonths: tx.isTransfer ? null : tx.spreadMonths,
            isTransfer: tx.isTransfer,
          );
      // The rule applies retroactively, so other transactions moved with it.
      ref.invalidate(categoryRulesProvider);
      ref.invalidate(transactionsProvider);
      ref.invalidate(spendingReportProvider);
      messenger.showSnackBar(
        SnackBar(content: Text('Rule "${rule.matchText}" now points at $target')),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// Snackbar action: let Gemini find transactions similar to the one just
  /// re-labeled and fix them too, after review in [AiRelabelSheet].
  void _offerAiFix(NavigatorState navigator, ScaffoldMessengerState messenger,
      TransactionRecord updated) {
    messenger.showSnackBar(SnackBar(
      content: Text('Categorized as ${updated.categoryName}'),
      action: SnackBarAction(
        label: 'Fix similar',
        onPressed: () async {
          final fixed = await showModalBottomSheet<int>(
            context: navigator.context,
            showDragHandle: true,
            isScrollControlled: true,
            builder: (_) => AiRelabelSheet(
              transactionId: updated.id,
              categoryName: updated.categoryName!,
            ),
          );
          if (fixed != null && fixed > 0) {
            messenger.showSnackBar(SnackBar(
              content: Text(
                  'Fixed $fixed similar transaction${fixed == 1 ? '' : 's'}'),
            ));
          }
        },
      ),
    ));
  }
}

/// What the bottom sheet resolved to: a category assignment, a transfer flip,
/// a spread, or opening the rule editor for this booking.
class _SheetChoice {
  final int? categoryId;
  final bool? transferValue;
  final int? spreadMonths;
  final bool isRuleChoice;

  const _SheetChoice.category(this.categoryId)
      : transferValue = null,
        spreadMonths = null,
        isRuleChoice = false;
  const _SheetChoice.transfer(this.transferValue)
      : categoryId = null,
        spreadMonths = null,
        isRuleChoice = false;
  const _SheetChoice.spread(this.spreadMonths)
      : categoryId = null,
        transferValue = null,
        isRuleChoice = false;
  const _SheetChoice.rule()
      : categoryId = null,
        transferValue = null,
        spreadMonths = null,
        isRuleChoice = true;

  bool get isTransferChoice => transferValue != null;
  bool get isSpreadChoice => spreadMonths != null;

  /// Note a category choice can carry a null id — that clears the category.
  bool get isCategoryChoice =>
      !isTransferChoice && !isSpreadChoice && !isRuleChoice;
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
