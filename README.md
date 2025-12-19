# 🎮 Pokemon Stock Monitor

Beat the scalpers! Monitor Pokemon TCG product availability across multiple retailers with instant alerts.

## 🎯 How Stock Bots Work (Now You Know!)

Those Twitter accounts that instantly tweet when products restock? They use bots like this that:

1. **Scrape product pages** every 30-60 seconds
2. **Detect button changes** - "Add to Cart" appears = IN STOCK!
3. **Check API endpoints** - Some sites have hidden inventory APIs
4. **Monitor price updates** - Price changes often signal restocking
5. **Send instant alerts** - Discord webhooks, notifications, auto-open browser

**Common restock patterns:**
- **Target**: 6:00 AM - 8:00 AM ET (weekdays)
- **Best Buy**: Random drops, often Tuesday/Thursday mornings
- **Pokemon Center**: Random (sometimes midnight ET)
- **GameStop**: Usually 11:00 AM - 1:00 PM ET

## ✨ Features

- 🔍 **Multi-Store Monitoring**: Target, Best Buy, Pokemon Center, GameStop, Amazon
- 🔔 **Instant Alerts**: Desktop notifications + sound when stock detected
- 🚀 **Auto Browser Open**: Opens product page automatically when in stock
- 📊 **Price Tracking**: Monitors price changes (sometimes signals restock)
- ⏰ **Restock History**: Tracks when products come back in stock
- 💾 **Activity Logging**: See exactly when you missed it
- 🎨 **Clean Terminal UI**: Real-time status with emojis
- ⚙️ **Configurable**: Adjust check intervals, alert sounds, etc.

## 📋 Requirements

- Python 3.8+
- macOS (uses native desktop notifications)
- Internet connection

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Add Products to Monitor

Edit `watchlist.txt` and add product URLs (one per line):

```
# Format: One URL per line
# Lines starting with # are comments

https://www.target.com/p/pokemon-tcg-prismatic-evolutions-elite-trainer-box/-/A-12345678
https://www.bestbuy.com/site/pokemon-tcg-prismatic-evolutions-booster-bundle/6789012.p
https://www.pokemoncenter.com/product/290-12345/pokemon-tcg-prismatic-evolutions-booster-box
```

### 3. Run the Monitor

```bash
python stock_monitor.py
```

The bot will:
- ✅ Check all products every 60 seconds (default)
- 🔔 Alert you immediately when stock appears
- 🚀 Auto-open browser to the product page
- 📝 Log all activity to `stock_log.txt`

## ⚙️ Configuration

Edit settings in `config.py`:

```python
# Check interval (seconds)
CHECK_INTERVAL = 60  # Check every 60 seconds

# Alert settings
PLAY_SOUND = True    # Play sound on stock alert
AUTO_OPEN_BROWSER = True  # Auto-open product page

# Discord webhook (optional - for mobile alerts)
DISCORD_WEBHOOK_URL = ""  # Add your Discord webhook
```

## 📱 Discord Integration (Optional)

Get mobile alerts by setting up a Discord webhook:

1. Create a Discord server (or use existing)
2. Create a webhook: Server Settings → Integrations → Webhooks → New Webhook
3. Copy webhook URL
4. Add to `config.py`:
   ```python
   DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
   ```

Now you'll get alerts on your phone via Discord!

## 🎯 Supported Stores

| Store | Status | Notes |
|-------|--------|-------|
| Target | ✅ | Checks "Add to Cart" button |
| Best Buy | ✅ | Monitors "Add to Cart" availability |
| Pokemon Center | ✅ | Detects "Out of Stock" vs available |
| GameStop | ✅ | Checks button status |
| Amazon | ⚠️ | Requires anti-bot bypass (advanced) |

## 📊 Example Output

```
============================================================
🎮 POKEMON STOCK MONITOR - ACTIVE
============================================================

🔍 Monitoring 3 products...
⏰ Check interval: 60 seconds
🔔 Alerts: Enabled
🚀 Auto-open: Enabled

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[10:15:30] Target - Prismatic Evolutions ETB
           Status: OUT OF STOCK
           Price: $49.99
           Last Check: Just now

[10:15:32] Best Buy - Prismatic Evolutions Booster Bundle  
           Status: OUT OF STOCK
           Price: $149.99
           Last Check: Just now

[10:15:34] Pokemon Center - Prismatic Evolutions Booster Box
           Status: OUT OF STOCK
           Price: $159.99
           Last Check: Just now
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⏳ Next check in 60 seconds...

🚨🚨🚨 ALERT! PRODUCT IN STOCK! 🚨🚨🚨

Target - Prismatic Evolutions ETB
💰 Price: $49.99
🔗 https://target.com/...

🚀 Opening browser...
```

## 🛠️ How It Works (Technical Details)

### Detection Methods

**1. Button Text Analysis**
- Looks for "Add to Cart", "Add to Bag", "Buy Now"
- Out of stock shows: "Out of Stock", "Sold Out", "Unavailable"

**2. Price Monitoring**
- Tracks price changes
- Price updates often happen before restocking

**3. Page Structure**
- Monitors specific HTML elements
- Detects when stock-related elements appear/disappear

**4. Response Time**
- Some sites return different HTTP codes when out of stock
- 200 OK + cart button = likely in stock

### Anti-Detection

**User-Agent Rotation**: Mimics real browsers
```python
'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...'
```

**Random Delays**: Varies check timing slightly to avoid patterns

**Respectful Scraping**: Default 60s interval (not aggressive)

## ⚠️ Important Notes

### Legal & Ethical
- ✅ **Legal**: Web scraping for personal use is generally legal
- ✅ **Respectful**: Default 60s interval doesn't overload servers
- ❌ **Don't**: Use this for scalping/reselling
- ❌ **Don't**: Set interval below 30 seconds (be respectful)

### Limitations
- **Captchas**: Some sites use captchas (manual solve needed)
- **Anti-bot measures**: Amazon has strong anti-bot (harder to scrape)
- **Rate limiting**: Sites may temporarily block if you check too frequently
- **No auto-checkout**: This monitors only - you still need to checkout manually

### Bot Detection Risks
If you see errors like "Access Denied" or captchas:
- Increase `CHECK_INTERVAL` to 120+ seconds
- Use a VPN (rotate IP)
- Clear browser cookies
- Wait a few hours before trying again

## 🎓 Learning Insights

After running this, you'll understand:
- How stock monitoring bots detect availability
- Why Twitter bots can alert so fast (they're checking constantly!)
- When stores typically restock (you'll see the patterns)
- How scalpers get products first (bots + fast checkout scripts)

## 📈 Advanced Features (DIY)

Want to level up? Add these features:

1. **Auto-Checkout Bot**: Use Selenium to automate checkout (risky!)
2. **Proxy Rotation**: Rotate IPs to avoid detection
3. **Captcha Solving**: Integrate 2Captcha API
4. **Multiple Accounts**: Check out faster with saved payment info
5. **Telegram Alerts**: Alternative to Discord
6. **Historical Analysis**: Track restock patterns with ML

## 🤝 Contributing

This is a personal project, but feel free to:
- Report issues
- Suggest features
- Share your restock time findings!

## 📝 Log Files

- `stock_log.txt` - All activity (checks, alerts, errors)
- `restock_history.json` - When products came back in stock

## 🎮 Pro Tips

1. **Run 24/7**: Leave it running on a spare computer or Raspberry Pi
2. **Multiple Discord Channels**: Different webhooks for different product types
3. **Learn the Patterns**: Check `restock_history.json` to see when stores typically restock
4. **Set Price Alerts**: Get notified when prices drop too
5. **Use Mobile Discord**: Get alerts anywhere
6. **Join Communities**: Pokemon TCG Discord servers often share restock info

## 💡 Why This Matters

Pokemon TCG products sell out in **minutes** during releases. By the time you manually check:
- Scalpers already bought everything (using bots like this)
- Twitter alerts are 30+ seconds old
- Products are already gone

**With this bot:**
- ⚡ You check **every 60 seconds** automatically
- 🔔 Get alerted **instantly** when stock appears
- 🚀 Browser opens **automatically** - just checkout!

Level the playing field against scalpers.

## 📞 Support

Having issues? Check:
1. Product URLs are correct and accessible
2. Internet connection is stable
3. `requirements.txt` dependencies are installed
4. Check `stock_log.txt` for error messages

## 🙏 Disclaimer

This tool is for **personal use only**. Use responsibly and ethically:
- Don't overload store servers (keep interval at 60s+)
- Don't use for commercial scalping/reselling
- Respect store Terms of Service
- Be a good community member

---

**Happy hunting! May the RNG gods bless your pulls! 🎴✨**
