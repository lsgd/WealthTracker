import 'package:flutter_test/flutter_test.dart';

import 'package:wealth_tracker/data/repositories/spending_repository.dart';

void main() {
  group('categorySortKey', () {
    test('sorts case-insensitively', () {
      final names = ['Transport', 'eBay', 'Groceries', 'zoo', 'Insurance']
        ..sort((a, b) => categorySortKey(a).compareTo(categorySortKey(b)));
      // A byte-wise compareTo would strand 'eBay' and 'zoo' behind 'Transport'.
      expect(names, ['eBay', 'Groceries', 'Insurance', 'Transport', 'zoo']);
    });

    test('files umlauts with their base letter, not after z', () {
      final names = ['Zoo', 'Ärzte', 'Öl', 'Bank', 'Übrig']
        ..sort((a, b) => categorySortKey(a).compareTo(categorySortKey(b)));
      expect(names, ['Ärzte', 'Bank', 'Öl', 'Übrig', 'Zoo']);
    });

    test('ß counts as ss', () {
      expect(categorySortKey('Straße'), 'strasse');
    });
  });
}
