import 'package:intl/intl.dart';

/// Currency formatter for displaying monetary values.
/// Displays whole numbers only (floored).
String formatCurrency(double value, String currency) {
  final format = NumberFormat.currency(
    locale: 'de_CH',
    symbol: currency,
    decimalDigits: 0,
  );
  return format.format(value.floor());
}

/// Exact currency formatter for single transactions (2 decimals).
///
/// The API serializes amounts with 4 decimal places ("-19.9000") — never show
/// that raw string.
String formatCurrencyExact(double value, String currency) {
  final format = NumberFormat.currency(
    locale: 'de_CH',
    symbol: currency,
    decimalDigits: 2,
  );
  return format.format(value);
}

/// Compact currency formatter for large values.
String formatCurrencyCompact(double value, String currency) {
  final format = NumberFormat.compactCurrency(
    locale: 'de_CH',
    symbol: currency,
    decimalDigits: 0,
  );
  return format.format(value);
}

/// Compact number formatter for chart axis (no currency symbol).
/// Uses the SMALLEST decimal count (0, 1 or 2) at which the tick [step] is
/// exactly representable in the suffix unit, so all labels of an axis share
/// the same decimals and stay distinct — step 2.5M gives "2.5M …10.0M" (not a
/// wrongly rounded "3M", and not an overlong "10.00M").
String formatChartAxisValue(double value, {double? step}) {
  int decimalsFor(double unit) {
    final ratio = (step ?? value) / unit;
    if ((ratio - ratio.roundToDouble()).abs() < 1e-9) return 0;
    final tenths = ratio * 10;
    if ((tenths - tenths.roundToDouble()).abs() < 1e-9) return 1;
    return 2;
  }

  if (value.abs() >= 1000000) {
    return '${(value / 1000000).toStringAsFixed(decimalsFor(1000000))}M';
  } else if (value.abs() >= 1000) {
    return '${(value / 1000).toStringAsFixed(decimalsFor(1000))}K';
  }
  return value.toStringAsFixed(0);
}

/// IBAN lengths per country, for [stripLeadingIban].
const _ibanLengths = {
  'AT': 20, 'BE': 16, 'BG': 22, 'CH': 21, 'CY': 28, 'CZ': 24, 'DE': 22,
  'DK': 18, 'EE': 20, 'ES': 24, 'FI': 18, 'FR': 27, 'GB': 22, 'GR': 27,
  'HR': 21, 'HU': 28, 'IE': 22, 'IT': 27, 'LI': 21, 'LT': 20, 'LU': 20,
  'LV': 21, 'MT': 31, 'NL': 18, 'NO': 15, 'PL': 28, 'PT': 25, 'RO': 24,
  'SE': 24, 'SI': 19, 'SK': 24,
};

/// True when [candidate] passes the IBAN mod-97 checksum.
bool _isValidIban(String candidate) {
  // Rearrange (first 4 chars to the end), letters -> 10..35, running mod 97.
  final rearranged = candidate.substring(4) + candidate.substring(0, 4);
  var remainder = 0;
  for (final unit in rearranged.codeUnits) {
    final int value;
    if (unit >= 0x30 && unit <= 0x39) {
      value = unit - 0x30;
    } else if (unit >= 0x41 && unit <= 0x5A) {
      value = unit - 0x41 + 10;
    } else {
      return false;
    }
    remainder = value < 10
        ? (remainder * 10 + value) % 97
        : (remainder * 100 + value) % 97;
  }
  return remainder == 1;
}

/// Strip a leading IBAN from a counterparty string.
///
/// Some feeds (DKB via FinTS) deliver the counterparty as `<IBAN><name>` in
/// one field — "DE9612…0904WERTGARANTIE". The IBAN adds nothing on screen, so
/// drop it and keep the name. Only a checksum-valid IBAN of the country's
/// exact length is stripped; anything else (including names that merely start
/// with two capitals and digits) stays untouched.
String stripLeadingIban(String raw) {
  if (raw.length < 15) return raw;
  final length = _ibanLengths[raw.substring(0, 2)];
  if (length == null || raw.length < length) return raw;
  final candidate = raw.substring(0, length);
  if (!RegExp(r'^[A-Z]{2}\d{2}[A-Z0-9]+$').hasMatch(candidate)) return raw;
  if (!_isValidIban(candidate)) return raw;
  return raw.substring(length).trim();
}

/// Date formatter for snapshot dates.
/// [formatSetting] can be: 'system', 'dmy', 'mdy', 'ymd'
String formatDate(DateTime date, [String formatSetting = 'system']) {
  final pattern = _getDatePattern(formatSetting);
  return DateFormat(pattern).format(date);
}

/// Get the date pattern for a given format setting.
String _getDatePattern(String formatSetting) {
  switch (formatSetting) {
    case 'dmy':
      return 'dd.MM.yyyy';
    case 'mdy':
      return 'MM/dd/yyyy';
    case 'ymd':
      return 'yyyy-MM-dd';
    case 'system':
    default:
      // Use system locale - yMd gives locale-appropriate format
      return 'yMd';
  }
}

/// Get display name for a date format setting.
String getDateFormatDisplayName(String formatSetting) {
  switch (formatSetting) {
    case 'dmy':
      return 'DD.MM.YYYY';
    case 'mdy':
      return 'MM/DD/YYYY';
    case 'ymd':
      return 'YYYY-MM-DD';
    case 'system':
    default:
      return 'System Default';
  }
}

/// Short date formatter for compact displays (e.g., "Jan 31" or "31 Jan").
String formatDateShort(DateTime date) {
  return DateFormat('d MMM').format(date);
}

/// Date formatter for API requests.
String formatDateForApi(DateTime date) {
  return DateFormat('yyyy-MM-dd').format(date);
}

/// Percentage formatter.
String formatPercentage(double value) {
  final sign = value >= 0 ? '+' : '';
  return '$sign${value.toStringAsFixed(2)}%';
}

/// Smart date formatter with relative time for recent dates.
/// Returns "today, date", "yesterday, date", "X days ago, date" for recent,
/// or just the date for older dates.
String formatDateSmart(DateTime date, [String formatSetting = 'system']) {
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final dateOnly = DateTime(date.year, date.month, date.day);
  final difference = today.difference(dateOnly).inDays;

  final formattedDate = formatDate(date, formatSetting);

  if (difference == 0) {
    return 'today, $formattedDate';
  } else if (difference == 1) {
    return 'yesterday, $formattedDate';
  } else if (difference >= 2 && difference <= 6) {
    return '$difference days ago, $formattedDate';
  } else if (difference == 7) {
    return '1 week ago, $formattedDate';
  } else {
    return formattedDate;
  }
}
