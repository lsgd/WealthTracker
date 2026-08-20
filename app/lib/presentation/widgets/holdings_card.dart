import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/utils/formatters.dart';
import '../providers/wealth_provider.dart';

const _assetClassLabels = {
  'equity': 'Equity',
  'fixed_income': 'Fixed income',
  'cash': 'Cash',
  'real_estate': 'Real estate',
  'commodity': 'Commodities',
  'crypto': 'Crypto',
  'other': 'Other',
};

/// Per-asset holdings, merged across accounts. Renders nothing until a
/// positions-capable broker (IBKR, Morgan Stanley) has synced — most setups
/// start without any, and an empty card would just be noise.
class HoldingsCard extends ConsumerWidget {
  const HoldingsCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final holdings = ref.watch(wealthHoldingsProvider);

    return holdings.when(
      loading: () => const SizedBox.shrink(),
      error: (_, _) => const SizedBox.shrink(),
      data: (report) {
        if (report.holdings.isEmpty) return const SizedBox.shrink();
        final theme = Theme.of(context);

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text('Holdings', style: theme.textTheme.titleMedium),
                    const Spacer(),
                    if (report.asOf != null)
                      Text(
                        'as of ${report.asOf}',
                        style: theme.textTheme.bodySmall,
                      ),
                  ],
                ),
                const SizedBox(height: 8),
                for (final holding in report.holdings)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                holding.name.isEmpty
                                    ? holding.symbol
                                    : holding.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              Text(
                                [
                                  if (holding.symbol.isNotEmpty) holding.symbol,
                                  _assetClassLabels[holding.assetClass] ??
                                      holding.assetClass,
                                  holding.accounts.join(', '),
                                ].join(' · '),
                                style: theme.textTheme.bodySmall,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 12),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              formatCurrency(
                                holding.valueBaseCurrency,
                                report.baseCurrency,
                              ),
                              style: theme.textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            Text(
                              '${holding.percentage.toStringAsFixed(1)}%',
                              style: theme.textTheme.bodySmall,
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
