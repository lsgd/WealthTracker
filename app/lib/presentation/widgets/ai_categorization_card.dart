import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models/ai_categorization.dart';
import '../providers/spending_provider.dart';
import '../screens/ai_suggestions_screen.dart';

String formatModelPrice(double? input, double? output) {
  if (input == null) return 'pricing not listed';
  return '\$$input in / \$$output out per 1M tokens';
}

String formatCheckedAt(String iso) {
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return iso;
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  final local = parsed.toLocal();
  return '${local.day} ${months[local.month - 1]} ${local.year}';
}

/// Shows which Gemini model is configured and starts a suggestion round.
///
/// Deliberately read-only: the API key and model are configured in the web app
/// only. The app never asks for the key — it just uses what is already stored
/// (encrypted) on the server.
class AiCategorizationCard extends ConsumerWidget {
  const AiCategorizationCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(aiConfigProvider);

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('AI categorization (Gemini)',
              style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          config.when(
            loading: () => const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            ),
            error: (e, _) => Text('$e'),
            data: (data) => _Body(config: data),
          ),
        ],
      ),
    );
  }
}

class _Body extends StatelessWidget {
  final AiConfig config;
  const _Body({required this.config});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (!config.configured) {
      return Text(
        'Not set up. Add your Gemini API key and pick a model in the web app; '
        'suggestions can then be requested from here.',
        style: theme.textTheme.bodyMedium,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (config.pricing != null)
          Card(
            margin: EdgeInsets.zero,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(config.pricing!.displayName,
                      style: theme.textTheme.titleMedium),
                  Text(
                    formatModelPrice(config.pricing!.inputPricePer1m,
                        config.pricing!.outputPricePer1m),
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: const Color(0xFF34D399)),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${config.model} · prices checked '
                    '${formatCheckedAt(config.pricing!.checkedAt)}',
                    style: theme.textTheme.labelSmall,
                  ),
                  const SizedBox(height: 2),
                  Text('Key and model are managed in the web app.',
                      style: theme.textTheme.labelSmall),
                ],
              ),
            ),
          ),
        const SizedBox(height: 12),
        // Same disclosure as the web UI, from the same server-side list.
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border:
                Border.all(color: theme.colorScheme.primary.withValues(alpha: 0.4)),
            color: theme.colorScheme.primary.withValues(alpha: 0.06),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Data sent to Google when you request suggestions:',
                  style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12)),
              const SizedBox(height: 4),
              for (final field in config.disclosedFields)
                Text('• $field', style: theme.textTheme.labelSmall),
              const SizedBox(height: 6),
              Text(
                'Not transferred: account numbers/IBANs, booking dates, balances, '
                'or your identity. Suggestions are never applied without your '
                'confirmation.',
                style: theme.textTheme.labelSmall,
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        // Two separate flows: reusable rules for recurring merchants, and
        // one-off category labels for whatever rules cannot catch.
        Text(
          '"Suggest rules" proposes reusable rules for recurring merchants '
          '(categorizing future transactions without AI); "Categorize items" '
          'labels the remaining one-off transactions. You review every '
          'proposal before it is applied.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(
                      builder: (_) => const AiSuggestionsScreen(
                          mode: AiSuggestMode.items)),
                ),
                icon: const Icon(Icons.auto_awesome, size: 18),
                label: const Text('Categorize items'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: FilledButton.icon(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(
                      builder: (_) => const AiSuggestionsScreen(
                          mode: AiSuggestMode.rules)),
                ),
                icon: const Icon(Icons.auto_awesome, size: 18),
                label: const Text('Suggest rules'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
