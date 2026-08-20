# Changelog

## Next: 1.4.0

- Transactions can now be marked as transfers by hand (checkbox in the web transaction list, switch in the app's category sheet), excluding them from the spending report — needed for broker funding that auto-detection cannot pair
- Importing historical transactions now reports the date range the bank actually served and warns when it is shorter than requested
- Syncs for brokers that report holdings (IBKR, Morgan Stanley) now record per-asset positions; a Holdings card on the dashboard (web and app) shows them merged across accounts
- New wealth simulation (chart icon on the start screen): Monte Carlo projection of total wealth with percentile bands, in today's purchasing power; defaults derived from your accounts, spending, and holdings, all adjustable, with an optional target amount and the probability of reaching it
- Simulation assumptions you change are saved to your profile and shared between web and app; assumptions you leave untouched keep updating from your data, and clearing a field goes back to the derived value

- Start screen now refreshes automatically after an automatic sync or after adding a snapshot from the account detail screen (no more pull-to-refresh needed)
- A "Syncing accounts" bar below the app bar now shows while a Sync All run is in progress, including automatic syncs on app open
- Sync results (synced count or per-account errors) are now also shown after automatic syncs
- New Spending screen (chart icon on the start screen): month-to-month spending by category, with a normalized view that spreads yearly bills across their months, and a per-month breakdown you can step through
- Spending screen now has a Transactions tab: pick an account and assign a category to any transaction by tapping it
- Spending settings (tune icon): manage categorization rules including drag-to-reorder, and request Gemini category suggestions to review and confirm (the Gemini key and model are still configured in the web app)
- Bug fixes and improvements.

## 1.3.8
- Added Zürcher Kantonalbank (ZKB) as a broker: accounts connect via EBICS and sync end-of-day balances. EBICS credentials are set up once on the web app (one-time key exchange) and shared across all your ZKB accounts.
- A ZKB account behaves like a manual account until its EBICS key exchange is activated by the bank: it prompts you to add snapshots by hand instead of showing a sync action that would fail.
- Bug fixes and improvements.

## Next: 1.3.7

- Bug fixes and improvements.

## 1.3.6

- Sync reminder can now repeat every day, every 3 days, weekly, or monthly (default every 3 days) instead of only daily
- New option to shift reminders that fall on a weekend to the next weekday, with an optional setting to also skip US market holidays (e.g. Good Friday, Christmas)
- Per-account chart y-axis now adapts to the visible value range with clean tick steps (100, 250, 500, 1k, 2.5k, 5k, 10k, ...)
- Per-account chart now loads the full snapshot history instead of just the most recent 100 entries
- Chart y-axis labels switch to 2 decimals (e.g. "13.20K", "1.25M") when step size would otherwise produce duplicate-looking ticks

## 1.3.5

- Stability improvements
- Tap an account card to view its history, balance chart, and full snapshot list

## 1.3.4

- Upgrade dependencies to the latest versions
- Quick snapshot sheet auto-closes after the last account is submitted
- 30-day chart range now forces daily granularity; previous setting restored when switching back
- Chart performance improved with downsampling for large datasets
- Y-axis labels always show 2 decimal places for million values
- Monthly aggregation method (last/min/max/avg) is now a user setting
- Sync no longer blocks the UI — graphs and manual data work while syncing
