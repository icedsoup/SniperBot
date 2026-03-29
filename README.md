# KarutaSniper

KarutaSniper is a self-bot that watches Karuta card drops in Discord, OCRs them, and automatically claims the best match it finds.

## Requirements

- Python 3.10+
- A Discord account token

Install dependencies:

```bash
pip install -r requirements.txt
```

> EasyOCR will download its language model on first run. This is normal.

## Setup

1. Clone the repo.
2. Copy the example config:
   ```bash
   cp "config template.json" config.json
   ```
3. Open `config.json` and fill in your values (see Configuration below).
4. Add keywords to the files under `keywords/` (see Keyword files below).
5. Run the bot:
   ```bash
   python main.py
   ```

## Keyword files

Add names you want to snipe, one per line:

| File | Purpose |
|------|---------|
| `keywords/characters.txt` | Character names to claim |
| `keywords/animes.txt` | Series names to claim any card from |
| `keywords/charblacklist.txt` | Characters to never claim |
| `keywords/aniblacklist.txt` | Series to never claim from |

> The bot reloads all four files automatically when they change.

## Configuration

| Key | Description |
|-----|-------------|
| `token` | Your Discord user token |
| `servers` | List of server IDs to subscribe to |
| `channels` | List of channel IDs to watch for drops |
| `accuracy` | Fuzzy match threshold for keywords |
| `blaccuracy` | Fuzzy match threshold for blacklists |
| `check_print` | Enable claiming by low print number |
| `print_number` | Maximum print number to auto-claim |
| `wishlist_lookup` | Enable wishlist fallback via CardCompanion |
| `wishlist_watching_channels` | Channels where wishlist lookup is allowed |
| `min_wishlist` | Minimum wishlist count required to claim by wishlist |
| `autodrop` | Enable automatic `kd` drops |
| `autodropchannel` | Channel ID used for `kd`, `kcd`, and wishlist `clu` lookups |
| `dropdelay` | Base delay in seconds between drops |
| `randmin` / `randmax` | Random jitter range added to drop delay |
| `autofarm` | Enable automatic `kw` farming |
| `resourcechannel` | Channel ID used for autofarm |
| `lookup_delay` | Minimum seconds between consecutive `clu` lookups |
| `log_hits` | Write every grab attempt to `log.txt` |
| `log_collection` | Write successful collects to `log.txt` |
| `log_drops` | Show drop events in console |
| `log_grabs` | Show grab confirmations in console |
| `log_wishlist` | Show wishlist lookup results in console |
| `log_autodrop` | Show autodrop events in console |
| `log_kcd` | Show cooldown check results in console |
| `log_autofarm` | Show autofarm events in console |
| `timestamp` | Prefix console output with `HH:MM:SS` |
| `debug` | Print internal debug messages |
| `very_verbose` | Print OCR output and extra detail |
| `clear_console_on_start` | Clear terminal on startup |
| `update_check` | Check GitHub for newer versions |

## Wishlist lookup

When no keyword matches, the bot can fall back to CardCompanion's `clu` command to check wishlist counts. It will claim whichever unblacklisted card has the highest wishlist count above `min_wishlist`.

**Requirements:**
- CardCompanion must be in your server.
- Set `autodropchannel` to a channel where the bot can send messages.
- The bot expects CardCompanion's user ID to be `1380936713639166082`. If yours differs, update `CARDCOMPANION_ID` near the top of `main.py`.

## File structure

```
KarutaSniper/
├── main.py
├── console.py
├── requirements.txt
├── config.json          # your config
├── config template.json
├── keywords/
│   ├── characters.txt
│   ├── animes.txt
│   ├── charblacklist.txt
│   └── aniblacklist.txt
├── lib/
│   ├── api.py
│   ├── imageapi.py
│   └── ocr.py
└── temp/                # runtime OCR workspace
    └── char/
```

## Notes

- OCR is never perfect. The cleaner and more specific your keyword lists, the fewer false positives you will get.
- `log.txt` is created automatically at runtime when `log_hits` or `log_collection` is enabled.
- The `temp/` directory must exist before running. It is included in the repo via `.gitkeep` files.

## Disclaimer

Using self-bots violates Discord's Terms of Service. Use this at your own risk.
Be careful with leaking your token.
