import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/sync_provider.dart';

/// Live view of a sync-all run: what is still queued on top, what has already
/// finished below. Watches the sync state, so an account moves from one list
/// to the other as soon as the next poll reports it done.
class SyncProgressDialog extends ConsumerWidget {
  const SyncProgressDialog({super.key});

  static Future<void> show(BuildContext context) {
    return showDialog<void>(
      context: context,
      builder: (_) => const SyncProgressDialog(),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sync = ref.watch(syncAllProvider);
    final pending = sync.progress.where((a) => a.isPending).toList();
    final finished = sync.progress.where((a) => !a.isPending).toList();

    return AlertDialog(
      title: Row(
        children: [
          if (sync.isSyncing) ...[
            const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 12),
          ],
          Text(sync.isSyncing ? 'Syncing' : 'Sync finished'),
        ],
      ),
      content: SizedBox(
        width: double.maxFinite,
        child: sync.progress.isEmpty
            ? const Text('Starting…')
            : SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (pending.isNotEmpty) ...[
                      _SectionHeader(
                        label: 'In progress (${pending.length})',
                      ),
                      ...pending.map((a) => _ProgressRow(account: a)),
                    ],
                    if (pending.isNotEmpty && finished.isNotEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 8),
                        child: Divider(height: 1),
                      ),
                    if (finished.isNotEmpty) ...[
                      _SectionHeader(label: 'Finished (${finished.length})'),
                      ...finished.map((a) => _ProgressRow(account: a)),
                    ],
                  ],
                ),
              ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String label;

  const _SectionHeader({required this.label});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
      ),
    );
  }
}

class _ProgressRow extends StatelessWidget {
  final SyncAccountProgress account;

  const _ProgressRow({required this.account});

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 20,
            height: 20,
            child: Center(child: _leading(colorScheme)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(account.name, style: textTheme.bodyMedium),
                if (_subtitle.isNotEmpty)
                  Text(
                    _subtitle,
                    style: textTheme.bodySmall?.copyWith(
                      color: account.state == 'error'
                          ? colorScheme.error
                          : colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _leading(ColorScheme colorScheme) {
    switch (account.state) {
      case 'syncing':
        return const SizedBox(
          width: 14,
          height: 14,
          child: CircularProgressIndicator(strokeWidth: 2),
        );
      case 'done':
        return Icon(Icons.check_circle, size: 18, color: colorScheme.primary);
      case 'skipped':
        return Icon(Icons.remove_circle_outline,
            size: 18, color: colorScheme.onSurfaceVariant);
      case 'pending_2fa':
        return Icon(Icons.sms_outlined, size: 18, color: colorScheme.tertiary);
      case 'error':
        return Icon(Icons.error_outline, size: 18, color: colorScheme.error);
      default:
        return Icon(Icons.schedule,
            size: 18, color: colorScheme.onSurfaceVariant);
    }
  }

  String get _subtitle {
    if (account.message.isNotEmpty) return account.message;
    switch (account.state) {
      case 'waiting':
        return 'Waiting';
      case 'syncing':
        return 'Syncing…';
      case 'done':
        return 'Synced';
      default:
        return '';
    }
  }
}
